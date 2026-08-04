# Changelog - FRITZ!Box SMS & Calls Integration

## v1.2.8 (2026-08-04)

### 🔧 Correzioni
- **Flow target SMS manual-only**: rimossa la dipendenza da Mobile Device Info nel config subentry; aggiunta e modifica target ora richiedono solo inserimento manuale di nome e numero
- **Naming entità notify corretto**: evitata la duplicazione nel nome entità (`notify.nome_nome`) mantenendo il nome target una sola volta
- **Traduzioni aggiornate**: testi UI allineati al nuovo flusso manuale per add/reconfigure target

## v1.2.7 (2026-08-01)

### ✨ Nuove Funzionalità
- **Binary sensor disponibilità internet**: aggiunto `binary_sensor.fritz_automation_internet_connection_active` per segnalare se almeno un collegamento DSL/LTE è attivo
- **Informazioni WAN estese**: il coordinatore WAN espone ora anche lo stato `internet_connection_active` per supportare automazioni semplici e diagnostica
- **Aggiornamento documentazione**: README e changelog riflettono il nuovo sensore e il comportamento di disponibilità internet

## v1.2.2 (2026-06-04)

### ✨ Nuove Funzionalità
- **Sensore TR-064 ManufacturerName**: aggiunto `sensor.fritz_automation_manufacturer_name` tramite `DeviceInfo:1/GetInfo` (`NewManufacturerName`)
- **Nuovi sensori WAN TR-064** per analisi connessione:
	- `sensor.fritz_automation_connection_type`
	- `sensor.fritz_automation_access_technology`
	- `sensor.fritz_automation_dsl_link_state`
	- `sensor.fritz_automation_lte_link_state`
	- `sensor.fritz_automation_wan_failover_active`
- **Rilevazione best-effort DSL/LTE** con fallback su più servizi TR-064 (`WANCommonInterfaceConfig`, `WANDSLInterfaceConfig`, `Layer3Forwarding`, servizi mobile AVM)

## v1.2.1 (2026-05-19)

### ✨ Nuove Funzionalità
- **Selezione device da Mobile Device Info**: durante l'aggiunta o la modifica di un target SMS, è ora possibile scegliere il device da un dropdown che mostra tutti i device presenti in `sensor.mobile_devices_info` (con nome e numero di telefono)
- **Fallback manuale**: se `sensor.mobile_devices_info` non è presente, il selector viene saltato e si procede direttamente all'inserimento manuale di nome e numero
- **Compatibilità standalone**: l'integrazione funziona completamente anche senza Mobile Device Info

## v1.2.0 (2026-05-19)

### ✨ Nuove Funzionalità
- **Lookup automatico numero di telefono** dal sensor `sensor.mobile_devices_info`: durante l'aggiunta o la modifica di un target SMS, il numero viene pre-compilato automaticamente in base al nome del device
- **Label integrazione mancante**: se `sensor.mobile_devices_info` non è presente, viene mostrato un messaggio di errore rosso nel config flow
- **Label nessun numero**: se il device non ha un numero associato in Mobile Device Info, viene mostrata una nota informativa
- **Flusso di inserimento a due step**: prima si inserisce il nome del target, poi il numero viene cercato e pre-compilato (modificabile)

## v1.0.0 (2025-01-XX) - Release Finale

### 🎉 Nuove Funzionalità
- **Supporto chiamate telefoniche** tramite FritzConnection
- **Integrazione completa SMS + Calls** in un'unica componente
- **Libreria fritz_automation lib interna** - Indipendente da HACS
- **Eventi custom** per automazioni avanzate
- **Sensore call_status** per monitoraggio chiamate attive

### 🔧 Servizi Implementati
#### SMS
- `fritz_automation.get_sms` - Recupera SMS ed emette evento
- `fritz_automation.mark_sms_read` - Marca SMS come letto
- `fritz_automation.delete_sms` - Elimina SMS

#### Chiamate (modelli compatibili)
- `fritz_automation.make_call` - Effettua chiamata
- `fritz_automation.hangup_call` - Termina chiamata

### 📊 Sensori
- `sensor.fritz_automation_sms_count` - Conteggio SMS
- `sensor.fritz_automation_last_sms` - Dettagli ultimo SMS
- `sensor.fritz_automation_sms_targets` - Target SMS disponibili  
- `sensor.fritz_automation_call_status` - Stato chiamate attive

### ⚡ Eventi Custom
- `fritz_automation_sms_received` - Emesso alla ricezione SMS
- `fritz_automation_call_event` - Emesso per azioni di chiamata

### 🛠️ Miglioramenti Tecnici
- **Async-safe**: Tutte le chiamate sincrone gestite correttamente
- **Device info unificato**: Informazioni coerenti per tutti i sensori
- **Naming forzato**: Nomi entità stabili con prefisso `fritz_automation_`
- **Gestione errori robusta**: Fallback e logging dettagliato
- **Compatibilità mantenuta**: Automazioni esistenti continuano a funzionare

### 📋 Note Importanti
- **Indipendente da HACS**: Libreria integrata, nessuna dipendenza esterna
- **Compatibilità modelli**: Chiamate disponibili solo su FRITZ!Box con supporto telefonico
- **Parametri ignorati**: `caller_phone` e `call_id` nei servizi chiamata per compatibilità

---

## Versioni Precedenti

### v0.2.x - SMS Management
- Implementazione servizi SMS personalizzati
- Eventi custom per automazioni
- Gestione robusta errori

### v0.1.x - Initial Release  
- Fork dall'integrazione originale HACS
- Sensori SMS di base
- Configurazione via UI
