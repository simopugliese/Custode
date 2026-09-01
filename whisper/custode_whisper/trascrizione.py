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


def in_wav_16k(audio: bytes, impostazioni: ImpostazioniWhisper, cartella: Path) -> Path:
    """Converte qualunque formato in ciò che whisper.cpp accetta: WAV 16 kHz mono."""
    sorgente = cartella / "audio.in"
    sorgente.write_bytes(audio)
    destinazione = cartella / "audio.wav"
    _esegui(
        [
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
            "-f",
            "wav",
            str(destinazione),
        ],
        impostazioni.timeout_secondi,
    )
    return destinazione


def trascrivi(audio: bytes, impostazioni: ImpostazioniWhisper) -> str:
    """Da byte audio a testo. Solleva `ErroreTrascrizione` se non ci riesce."""
    if not audio:
        raise ErroreTrascrizione("audio vuoto")
    if len(audio) > impostazioni.max_byte_audio:
        raise ErroreTrascrizione("audio troppo lungo")

    with tempfile.TemporaryDirectory(prefix="custode-whisper-") as temporanea:
        cartella = Path(temporanea)
        wav = in_wav_16k(audio, impostazioni, cartella)
        risultato = _esegui(
            [
                str(impostazioni.binario),
                "--model",
                str(impostazioni.modello),
                "--language",
                impostazioni.lingua,
                "--threads",
                str(impostazioni.thread),
                "--no-timestamps",
                "--no-prints",
                "--output-txt",
                "--output-file",
                str(cartella / "out"),
                "--file",
                str(wav),
            ],
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
