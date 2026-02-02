# Manuale utente – Gestione Magazzino (Flask + SQLite)

## 1. Scopo del manuale
Questo manuale descrive in modo operativo tutte le funzioni disponibili nell'app Gestione Magazzino: catalogo pubblico, area amministratore, posizionamento nelle cassettiere, stampa etichette/cartellini, import/export, ruoli e permessi, integrazioni API e MQTT. Le istruzioni fanno riferimento al setup standard dell'app (Flask + SQLite) e includono casi d’uso tipici basati sul flusso reale dell’applicazione.

---

## 2. Prerequisiti e avvio
- **Tecnologie**: Python 3.10+, Flask, SQLAlchemy, Flask-Login, DataTables lato client.
- **Database**: SQLite in `instance/magazzino.db`.
- **Avvio**: `python magazzino.py` (porta predefinita `http://localhost:5000`).

Suggerimento operativo: usa lo script `start.sh` per creare/attivare il virtualenv, installare le dipendenze e avviare l’app in un solo passaggio.

---

## 3. Accesso e ruoli
- **Catalogo pubblico**: `http://localhost:5000`.
- **Area amministratore**: `http://localhost:5000/login`.
- **Credenziali iniziali**: utente `admin`, password `admin` (da cambiare al primo accesso). 

### 3.1 Registrazione utenti
La registrazione è disponibile dalla pagina di login. Il primo utente creato riceve ruolo **Admin**; gli utenti successivi vengono creati con ruolo **Lettore**, a meno che non vengano modificati dall’amministratore.

### 3.2 Profilo utente
Ogni utente autenticato può:
- Aggiornare nome, cognome, email e link social.
- Cambiare password.
- Impostare un avatar scegliendolo dalla libreria o caricando un file (PNG/JPG/WEBP).

---

## 4. Catalogo pubblico (homepage)
Il catalogo mostra tutti gli articoli e consente filtri rapidi:
- Ricerca testuale (nome, descrizione, filettatura).
- Categoria, sottotipo, materiale, finitura.
- Misura filettatura, presenza stock, condivisione cassetto.
- Filtro per posizione (cassettiera, riga, colonna).

Funzioni disponibili:
- **Ordinamento e filtro** tramite DataTables.
- **Stampa** etichette/cartellini per gli articoli selezionati.
- **Badge** di categoria, quantità e posizione.

---

## 5. Area amministratore
L’area admin è accessibile ai ruoli con i permessi adeguati. Le funzioni principali sono:

### 5.1 Dashboard / gestione articoli
- Creazione, modifica ed eliminazione articoli.
- Campi principali: categoria, sottotipo, filettatura, dimensioni principali, materiale, finitura, quantità, descrizione.
- Campi personalizzati configurabili per categoria (testo/numero/select).
- Flag “Condividi cassetto” per consentire la coesistenza di più articoli nello stesso slot.
- Scelta di cosa mostrare su etichetta (categoria, sottotipo, thread, misure, materiale).

### 5.2 Posizionamento e cassettiere
- **Vista Cassettiere**: griglia con righe/colonne, slot con etichette e contenuto.
- **Posizionamento manuale**: seleziona cassettiera, colonna e riga per un articolo.
- **Auto-assegna**: riempimento automatico di cassetti vuoti per categoria con criterio di ordinamento.
- **Blocco slot**: marca celle non utilizzabili.
- **Fusione cassetti**: unisci più celle per ospitare un cassetto più grande.

### 5.3 Configurazioni (admin config)
Nel pannello configurazione puoi gestire:
- **Tassonomie**: categorie, sottotipi, materiali, finiture.
- **Ubicazioni e cassettiere**: definisci luoghi fisici e dimensione della griglia (righe/colonne).
- **Campi personalizzati**: definisci nuovi campi e associane la visibilità alle categorie.
- **Etichette e cartellini**: dimensioni, margini, orientamento, QR, formato pagina (A4/A5/A3/Letter/Legal).
- **MQTT**: abilita l’invio automatico di payload su un topic configurabile.
- **Ruoli e permessi**: crea ruoli, assegna permessi, gestisci utenti (con vincoli di sicurezza per non rimuovere l’ultimo admin).

### 5.4 Import/Export
- **Export CSV articoli**: include anche posizione e attributi principali.
- **Export JSON completo**: esporta categorie, materiali, finiture, cassettiere, slot, articoli, assegnazioni e campi custom.
- **Import CSV**: aggiorna o crea articoli e può assegnare la posizione se la cassettiera esiste.
- **Import JSON**: ripristino completo dei dati esportati.

### 5.5 Stampa etichette e cartellini
- PDF multipagina con colori di categoria.
- QR opzionale verso l’endpoint JSON di ciascun articolo.
- Gestione di slot condivisi con stampa di un’etichetta unica “MULTY”.

---

## 6. API e integrazioni
### 6.1 API JSON articolo
Endpoint: `/api/items/<id>.json`

Restituisce:
- Dettagli articolo (nome, descrizione, dimensioni, materiale, finitura, quantità).
- Categoria e colore.
- Posizione completa (se assegnata).

### 6.2 API lookup slot
Endpoint: `/api/slots/lookup?cabinet_id=...&col_code=...&row_num=...`

Restituisce:
- Stato dello slot, etichetta e contenuto.
- Elenco articoli presenti nello slot.

### 6.3 MQTT
Se abilitato, il sistema pubblica gli slot secondo le impostazioni definite in admin config (topic, QoS, payload e campi inclusi).

---

## 7. Backup e sicurezza
- All’avvio e quotidianamente (se necessario) l’app genera un backup del database in `instance/backups/`.
- Mantiene un numero configurabile di backup (default 7). 
- Per sicurezza, cambia la password dell’utente admin al primo accesso.

---

## 8. Casi d’uso basati sul setup

### Caso d’uso 1 – Avvio rapido e primo inventario
**Scenario**: devi censire minuteria tecnica (viti, dadi, rondelle).
1. Avvia l’app (`python magazzino.py`) e apri `http://localhost:5000/login`.
2. Accedi con `admin/admin` e cambia la password dal profilo.
3. Vai in **Config** e crea le prime **Ubicazioni** (es. “Officina”), quindi le **Cassettiere** (es. “CAS-01”, righe 1..64, colonne A..Z).
4. Inserisci le **Categorie** necessarie (es. Viti, Dadi, Rondelle) e, se serve, aggiungi **Sottotipi**.
5. Dalla dashboard, crea i primi articoli e assegna subito una posizione (cassettiera + colonna + riga).
6. Apri la pagina **Cassettiere** per verificare visivamente gli slot occupati.

**Risultato**: inventario iniziale completo con posizioni assegnate e pronto per la stampa etichette.

### Caso d’uso 2 – Rifornimento rapido con scorte basse
**Scenario**: vuoi controllare articoli con quantità bassa.
1. Nel catalogo pubblico o in admin, usa il filtro **Stock: low**.
2. Ordina la tabella per quantità crescente.
3. Apri la scheda articolo e aggiorna la quantità.
4. (Opzionale) stampa nuove etichette selezionando gli articoli aggiornati.

**Risultato**: scorte riallineate e documentate con etichette coerenti.

### Caso d’uso 3 – Condivisione cassetto per articoli simili
**Scenario**: vuoi tenere in uno stesso slot rondelle e viti della stessa serie.
1. Per ogni articolo, attiva **Condividi cassetto**.
2. Assegna lo stesso slot a più articoli.
3. Stampa le etichette: il sistema genererà una singola etichetta “MULTY” per il cassetto condiviso.

**Risultato**: cassetto condiviso con etichetta unificata, senza sovraccarico visivo.

### Caso d’uso 4 – Importazione massiva da CSV
**Scenario**: hai un file CSV con articoli da un gestionale precedente.
1. Prepara il CSV con le colonne previste (id, categoria, subtype, thread_size, dimensioni, materiale, finitura, quantity, position).
2. Vai in **Admin → Importa dati** e seleziona formato CSV.
3. Carica il file; eventuali nuove categorie/materiali vengono create automaticamente.
4. Controlla gli avvisi (es. cassettiere non trovate).

**Risultato**: inventario importato e pronto per l’assegnazione slot.

### Caso d’uso 5 – Integrazione esterna tramite QR
**Scenario**: vuoi consultare dettagli articolo da mobile.
1. Configura in **Impostazioni** il QR attivo e, se necessario, imposta una base URL.
2. Stampa etichette o cartellini.
3. Scansiona il QR per aprire `/api/items/<id>.json`.

**Risultato**: accesso immediato ai dettagli articolo dal dispositivo mobile.

---

## 9. Suggerimenti operativi
- Definisci subito ubicazioni e cassettiere per evitare “posizioni generiche”.
- Usa campi personalizzati per informazioni specifiche (es. coppia serraggio, certificazioni).
- Mantieni le dimensioni etichette coerenti con il layout fisico delle stampanti.
- Esegui un export JSON prima di grandi importazioni o modifiche strutturali.

---

## 10. Glossario rapido
- **Categoria**: macro-tipo di articolo (es. Viti).
- **Sottotipo**: variante/formato della categoria (es. Vite a brugola).
- **Slot**: cella (riga + colonna) nella cassettiera.
- **Fusione**: unione di più slot per creare un cassetto più grande.
- **Etichetta**: stampa compatta con QR e colore categoria.
- **Cartellino**: stampa più grande con dettagli estesi.

---

Fine del manuale.
