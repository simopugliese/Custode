"""Invocazione di whisper.cpp, isolata dal servizio HTTP.

Tenere qui il pezzo che parla col binario rende testabile tutto il resto senza
avere whisper compilato, e lascia un punto solo da cambiare se un domani il
modello o il comando cambiano (§13 lo dà per scontato: "parametro facilmente
cambiabile in futuro").
"""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from custode_whisper.config import ImpostazioniWhisper

log = logging.getLogger("custode.whisper")


class ErroreTrascrizione(RuntimeError):
    """La trascrizione non è riuscita: audio illeggibile, o whisper in errore."""


def _esegui(comando: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(comando, capture_output=True, timeout=timeout, check=True)
    except FileNotFoundError as errore:
        raise ErroreTrascrizione(f"eseguibile non trovato: {comando[0]}") from errore
    except subprocess.TimeoutExpired as errore:
        raise ErroreTrascrizione("la trascrizione ha superato il tempo massimo") from errore
    except subprocess.CalledProcessError as errore:
        dettaglio = errore.stderr.decode("utf-8", "replace").strip()[-500:]
        raise ErroreTrascrizione(f"{Path(comando[0]).name} ha fallito: {dettaglio}") from errore


# Filtri applicati all'audio prima di darlo a whisper.cpp.
#
# Un vocale di Telegram non è una registrazione da studio: è registrato per
# strada, in tasca, a mezzo metro dalla bocca, spesso a volume basso. Whisper
# sbaglia molto di più su un segnale debole che su uno pulito, e questi due
# filtri costano qualche millisecondo di ffmpeg:
#
# - `highpass=f=80` toglie tutto sotto gli 80 Hz — traffico, vento sul
#   microfono, il rimbombo di una stanza. Nessuna voce umana ci arriva, quindi
#   non si perde parlato: si toglie solo ciò che copre le consonanti.
# - `dynaudnorm` porta il parlato a un volume costante **dentro** la
#   registrazione, invece di scalare tutto per lo stesso fattore: è il caso di
#   chi comincia forte e finisce a bassa voce, dove la coda della frase è la
#   parte che si perde.
FILTRI_AUDIO = "highpass=f=80,dynaudnorm"


def in_wav_16k(audio: bytes, impostazioni: ImpostazioniWhisper, cartella: Path) -> Path:
    """Converte qualunque formato in ciò che whisper.cpp accetta: WAV 16 kHz mono."""
    sorgente = cartella / "audio.in"
    sorgente.write_bytes(audio)
    destinazione = cartella / "audio.wav"
    comando = [
        str(impostazioni.ffmpeg),
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        str(sorgente),
        "-ar",
        "16000",
        "-ac",
        "1",
    ]
    if impostazioni.filtri_audio:
        comando += ["-af", impostazioni.filtri_audio]
    comando += ["-f", "wav", str(destinazione)]
    _esegui(comando, impostazioni.timeout_secondi)
    return destinazione


def comando_whisper(
    impostazioni: ImpostazioniWhisper, wav: Path, uscita: Path, contesto: str
) -> list[str]:
    """Gli argomenti di whisper.cpp, in una funzione pura che si può leggere.

    Sta a parte perché è la cosa che si sbaglia e che si vuole poter verificare
    senza avere il binario compilato.
    """
    comando = [
        str(impostazioni.binario),
        "--model",
        str(impostazioni.modello),
        "--language",
        impostazioni.lingua,
        "--threads",
        str(impostazioni.thread),
        "--no-timestamps",
        "--no-prints",
    ]
    if impostazioni.sopprimi_non_parlato:
        # Su una pausa lunga o un rumore di fondo Whisper tende a *inventare*:
        # in italiano tira fuori le frasi tipiche dei sottotitoli, che poi
        # arrivano all'interprete come se fossero state dette. Sopprimere i
        # token che non sono parlato taglia buona parte di quei casi.
        comando.append("--suppress-nst")
    if contesto:
        # `--prompt`, non `-p`: nella riga di comando di whisper.cpp `-p` è
        # `--processors`, e scriverlo per abbreviare farebbe partire un numero
        # di processi pari alla lunghezza del testo.
        comando += ["--prompt", contesto]
    comando += ["--output-txt", "--output-file", str(uscita), "--file", str(wav)]
    return comando


def trascrivi(audio: bytes, impostazioni: ImpostazioniWhisper, contesto: str = "") -> str:
    """Da byte audio a testo. Solleva `ErroreTrascrizione` se non ci riesce.

    `contesto` è l'elenco dei nomi che il proprietario usa davvero — abitudini,
    categorie di spesa, task aperti — passato a whisper.cpp come prompt
    iniziale. Serve perché Whisper indovina dal suono: senza, «Bricoman» esce
    «bricomane» e l'interprete non aggancia più niente. Chi chiama lo prepara
    (`custode_core.dominio.vocabolario`); qui si accetta anche vuoto, che è il
    comportamento di prima.
    """
    if not audio:
        raise ErroreTrascrizione("audio vuoto")
    if len(audio) > impostazioni.max_byte_audio:
        raise ErroreTrascrizione("audio troppo lungo")

    with tempfile.TemporaryDirectory(prefix="custode-whisper-") as temporanea:
        cartella = Path(temporanea)
        wav = in_wav_16k(audio, impostazioni, cartella)
        risultato = _esegui(
            comando_whisper(impostazioni, wav, cartella / "out", contesto.strip()),
            impostazioni.timeout_secondi,
        )
        trascritto = cartella / "out.txt"
        if trascritto.exists():
            testo = trascritto.read_text(encoding="utf-8", errors="replace")
        else:
            # Alcune build scrivono su stdout invece che sul file.
            testo = risultato.stdout.decode("utf-8", "replace")

    pulito = " ".join(testo.split())
    if not pulito:
        raise ErroreTrascrizione("non sono riuscito a capire l'audio")
    return pulito
