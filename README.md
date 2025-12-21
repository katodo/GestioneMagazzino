# Magazzino – Flask + SQLite

## Installazione
```bash
cd magazzino
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python magazzino.py
```

Apri `http://localhost:5000`.

- In alternativa puoi usare lo script `start.sh` che crea/attiva il virtualenv, installa le dipendenze e avvia l'app.

- Admin: `http://localhost:5000/login` (utente: `admin`, password: `admin`).
- Il DB SQLite è salvato in `instance/magazzino.db`.

## Funzioni incluse in questa versione
- Homepage pubblica con tabella filtrabile/ordinabile (DataTables).
- Admin:
  - Aggiunta articolo con **menu a tendina** per categoria, sottotipo, materiale, finitura.
  - Filettature **M / UNC / UNF** con **dropdown** della misura.
  - Selezione opzionale **Ubicazione/Cassettiera** + **Riga/Colonna** per assegnare subito la posizione.
  - **Checkbox** per scegliere i campi da mostrare in etichetta (per articolo).
  - **Modifica** ed **Elimina** articolo.
- API JSON: `/api/items/<id>.json` con posizione (se assegnata).

## Note
- È pre-caricata una Ubicazione “Parete A (PA)” e una Cassettiera “Cassettiera 1 (pair_code AA)”. Puoi crearne altre in una versione successiva.
- Le colonne accettano **A..Z** e **AA..ZZ**; righe 1..128.
- Uno **slot** può contenere più articoli **della stessa categoria** (viene usato il primo scomparto libero).

## Importazione database da versione precedente
1. **Ferma l'app** se è in esecuzione.
2. **Fai un backup** dell'attuale `instance/magazzino.db`.
3. Copia il database della versione precedente in `instance/magazzino.db`.
4. Avvia l'app con `./start.sh` oppure `python magazzino.py`.
   All'avvio vengono eseguite automaticamente le migrazioni leggere per aggiungere eventuali colonne mancanti.
