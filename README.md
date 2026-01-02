# Magazzino – Gestione inventario Flask + SQLite

Applicazione web per catalogare minuteria tecnica, assegnare articoli a cassettiere e stampare etichette o cartellini. L'interfaccia pubblica mostra l'inventario filtrabile, mentre l'area admin consente di gestire categorie, posizioni, campi personalizzati e impostazioni di stampa.

## Requisiti
- Python 3.10+ (Flask, SQLAlchemy, Flask-Login, DataTables lato client).
- Facoltativo per stampa: `reportlab` (incluso in `requirements.txt`) per generare PDF di etichette e cartellini.

## Installazione e avvio rapido
```bash
# da root del progetto
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python magazzino.py
```

Alternative: `./start.sh` crea/attiva il virtualenv, installa le dipendenze e avvia l'app in un unico passaggio. L'applicazione espone l'interfaccia su `http://localhost:5000`.

## Accesso
- Homepage pubblica: `http://localhost:5000` con tabella filtrabile/ordinabile (DataTables) e pulsanti per stampare etichette/cartellini degli articoli selezionati.
- Area amministratore: `http://localhost:5000/login` (default utente `admin`, password `admin`). Dopo l'accesso è disponibile la dashboard `/admin`.

## Struttura dati e salvataggio
- Database SQLite salvato in `instance/magazzino.db`. La cartella `instance/` viene creata automaticamente.
- Modelli principali: categorie, sottotipi, materiali, finiture, articoli, ubicazioni, cassettiere, slot, assegnazioni agli slot, campi personalizzati e impostazioni (etichette e MQTT).
- Migrazioni leggere: all'avvio vengono create le tabelle mancanti e aggiunte eventuali colonne nuove se non presenti.

## Flusso operativo (admin)
1. **Configura tassonomie**: crea categorie e sottotipi (forme), materiali e finiture da `/admin/config`.
2. **Definisci posizioni**: aggiungi ubicazioni e cassettiere (righe 1..128, colonne A..Z/AA..ZZ), unisci più celle se necessario e blocca gli slot inutilizzabili.
3. **Crea articoli**: da `/admin` compila categoria/sottotipo, standard filettatura (M/UNC/UNF) con misure suggerite, dimensioni principali, quantità e campi personalizzati. Puoi scegliere quali campi compaiono sulle etichette del singolo articolo.
4. **Assegna posizioni**: indica cassettiera/colonna/riga durante la creazione oppure usa le viste "Posizionamento" o "Auto-assegna" per riempire cassetti vuoti per categoria; gli slot possono ospitare più articoli compatibili se è spuntato "Condividi cassetto".
5. **Stampa**: seleziona articoli dall'elenco admin o pubblico e genera PDF di etichette (con QR verso l'API JSON) o cartellini. Le dimensioni, margini, orientamento e visibilità del QR si configurano da `/admin/config`.
6. **Esporta o integra**: scarica l'inventario CSV da `/admin/items/export` oppure integra sistemi esterni via API e MQTT.

## Funzioni principali
- **Catalogo pubblico**: lista filtrabile degli articoli con badge di categoria, quantità e posizione se assegnata. Export etichette/cartellini disponibile anche qui.
- **Dashboard admin**: KPI rapidi (articoli totali, categorie, scorte basse, articoli da posizionare) e form veloce per nuovo articolo con menu a tendina, datalist di misure e campi personalizzati.
- **Gestione posizioni**: griglia cassettiere, blocco/sblocco slot, merge di cassetti, assegnazioni manuali o automatiche con criteri di ordinamento e pulizia degli slot occupati.
- **Campi personalizzati**: crea campi testo/numero/select e abilitali per singola categoria; i valori sono salvati per articolo e possono comparire in stampa.
- **Etichette e cartellini**: PDF multipagina A4 con colori di categoria, QR opzionale verso `/api/items/<id>.json`, e riassunto multi-articolo per slot condivisi.
- **API e integrazioni**: endpoint JSON `/api/items/<id>.json` (inclusa posizione se presente) e `/api/slots/lookup` per cercare slot; pubblicazione opzionale via MQTT configurabile da `/admin/config` con payload personalizzabile.

## Configurazioni utili
- **Impostazioni etichette**: larghezza/altezza, margini, gap, padding, dimensione QR e blocco posizione. È possibile disattivare il QR o definire una base URL esterna per comporre il link nelle etichette.
- **MQTT**: abilita hostname/porta/credenziali, topic e payload (inclusioni selezionabili per slot, articolo e posizione). I pulsanti "Pubblica slot" e invio massivo usano queste impostazioni.
- **Soglia scorte basse**: regola il valore nella dashboard per evidenziare gli articoli da reintegrare.

## Backup e migrazione
1. Arresta l'applicazione se è in esecuzione.
2. Copia `instance/magazzino.db` in un percorso sicuro.
3. Per migrare da versioni precedenti, sostituisci il file con il backup e riavvia (`./start.sh` o `python magazzino.py`); all'avvio vengono applicate le migrazioni leggere.

## Suggerimenti
- Imposta subito nuove ubicazioni/cassettiere per evitare di condividere troppo i cassetti di default.
- Usa la stampa etichette con QR quando prevedi consultazione da dispositivi mobili o integrazione esterna: l'URL codificato restituisce i dettagli articolo in JSON.
- Se reportlab non è installato, l'app mostra un messaggio nella UI: installa con `pip install reportlab` nel virtualenv.
