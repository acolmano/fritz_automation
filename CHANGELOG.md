# Changelog - FRITZ!Box SMS & Calls Integration

## v1.0.0 (2025-01-XX) - Release Finale

### 🎉 Nuove Funzionalità
- **Supporto chiamate telefoniche** tramite FritzConnection
- **Integrazione completa SMS + Calls** in un'unica componente
- **Libreria pyfritzsms interna** - Indipendente da HACS
- **Eventi custom** per automazioni avanzate
- **Sensore call_status** per monitoraggio chiamate attive

### 🔧 Servizi Implementati
#### SMS
- `fritzsms.get_sms` - Recupera SMS ed emette evento
- `fritzsms.mark_sms_read` - Marca SMS come letto
- `fritzsms.delete_sms` - Elimina SMS

#### Chiamate (modelli compatibili)
- `fritzsms.make_call` - Effettua chiamata
- `fritzsms.hangup_call` - Termina chiamata

### 📊 Sensori
- `sensor.fritzsms_sms_count` - Conteggio SMS
- `sensor.fritzsms_last_sms` - Dettagli ultimo SMS
- `sensor.fritzsms_sms_targets` - Target SMS disponibili  
- `sensor.fritzsms_call_status` - Stato chiamate attive

### ⚡ Eventi Custom
- `fritzsms_sms_received` - Emesso alla ricezione SMS
- `fritzsms_call_event` - Emesso per azioni di chiamata

### 🛠️ Miglioramenti Tecnici
- **Async-safe**: Tutte le chiamate sincrone gestite correttamente
- **Device info unificato**: Informazioni coerenti per tutti i sensori
- **Naming forzato**: Nomi entità stabili con prefisso `fritzsms_`
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
