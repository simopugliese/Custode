# whisper — trascrizione vocale locale

Whisper gira qui dentro, sul Pi, in un container suo (ARCHITECTURE.md §4, §13).
I vocali non escono di casa: è la parte più letterale del "privacy first" di §1.

- `config.py` — binario, modello, lingua, thread, limiti.
- `trascrizione.py` — la conversione audio e l'invocazione di whisper.cpp.
- `main.py` — il servizio: `POST /trascrivi` e `GET /health`.

## Perché un container a sé

§13 chiede thread limitati e un CPU limit **sul container**, così una
trascrizione lunga non ruba risorse al bot e all'API. Con whisper dentro il
processo del bot quel limite non si potrebbe dare solo alla trascrizione.

Il servizio non è esposto: ascolta solo sulla rete interna di Docker, non passa
dal tunnel, e non ha autenticazione perché chi può raggiungerlo è già dentro
casa (§2, §9).

## Modello

`base` quantizzato q5_1, come da §13: circa 1 GB di RAM, pochi secondi per un
vocale di 30-60 secondi su un Pi 5, e con parlato pulito in ambiente silenzioso
l'accuratezza è già solida — i modelli più grandi servirebbero soprattutto a
compensare rumore di fondo. Si cambia con `WHISPER_MODELLO` e l'argomento
`WHISPER_MODEL` del build.

**Sul Pi vero, l'ultima frase regge solo a metà.** Un vocale si trascrive, nei
tempi previsti, ma a volte il testo non è quello che è stato detto. Era in parte
prevedibile — `base` è addestrato quasi tutto su inglese — e la taratura è un
lavoro aperto: le tre leve, e il modo di provarne una alla volta, stanno in
DEPLOY.md, «Se una trascrizione esce storta». Cambiarne due insieme non dice
quale ha funzionato.

## Il vocabolario di chi parla

`POST /trascrivi` accetta, oltre al file, un campo `contesto`: i nomi che il
proprietario usa davvero — abitudini, categorie di spesa, reparti, task aperti —
che finiscono nel `--prompt` di whisper.cpp.

Serve perché Whisper indovina le parole **dal suono**, e sui nomi propri
sbaglia in modo sistematico: «Bricoman» diventa «bricomane», «Analisi II»
diventa «analisi due». Sono esattamente le parole che poi servono all'interprete
per agganciare un'abitudine o una categoria che esiste già, quindi l'errore non
resta nella trascrizione: si propaga, e il messaggio non fa niente.

Il campo è **facoltativo** e il servizio resta **senza stato**: quei nomi stanno
nel database, che è del bot. Li manda lui insieme all'audio invece di far
montare il database anche a questo container. L'elenco lo prepara
`custode_core.dominio.vocabolario`, tagliato a 400 caratteri — whisper.cpp
tiene al massimo `n_text_ctx/2` token, ma il motivo vero del tetto è un altro:
più parole si suggeriscono, più il modello è disposto a *produrle* anche quando
non le ha sentite.

Attenzione al nome del flag: nella riga di comando di whisper.cpp `-p` è
`--processors`, non `--prompt`.

## Formato audio

I vocali di Telegram sono OGG/Opus; whisper.cpp vuole WAV 16 kHz mono. La
conversione la fa ffmpeg, incluso nell'immagine.

Prima di trascrivere l'audio viene anche **ripulito** (`WHISPER_FILTRI_AUDIO`,
di default `highpass=f=80,dynaudnorm`): un vocale di Telegram è registrato per
strada, in tasca, spesso a volume basso, e Whisper sbaglia molto di più su un
segnale debole. Il passa-alto toglie ciò che sta sotto la voce umana — traffico,
vento, rimbombo — e `dynaudnorm` porta il parlato a un volume costante *dentro*
la registrazione, che è il caso di chi comincia forte e finisce piano.

Infine `--suppress-nst`: su silenzio e rumore Whisper inventa, e in italiano
tira fuori le frasi tipiche dei sottotitoli, che poi arrivano all'interprete
come se fossero state dette. La VAD sarebbe il rimedio pulito, ma non c'è in
whisper.cpp v1.7.4 — il pin è nel Dockerfile.

## Provarlo

```bash
docker compose up -d whisper
curl -F "audio=@vocale.ogg" http://127.0.0.1:8100/trascrivi
```

(la porta è pubblicata su loopback solo se la si aggiunge al compose per fare
prove: in esercizio il servizio parla solo con il bot, sulla rete interna)
