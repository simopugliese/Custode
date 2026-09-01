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

## Formato audio

I vocali di Telegram sono OGG/Opus; whisper.cpp vuole WAV 16 kHz mono. La
conversione la fa ffmpeg, incluso nell'immagine.

## Provarlo

```bash
docker compose up -d whisper
curl -F "audio=@vocale.ogg" http://127.0.0.1:8100/trascrivi
```

(la porta è pubblicata su loopback solo se la si aggiunge al compose per fare
prove: in esercizio il servizio parla solo con il bot, sulla rete interna)
