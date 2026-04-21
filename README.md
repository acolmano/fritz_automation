# FRITZ!Box SMS & Calls Integration

Integrazione custom per Home Assistant che supporta **SMS e chiamate telefoniche** tramite FRITZ!Box, completamente indipendente da HACS.

## ✨ Caratteristiche

### 📱 Gestione SMS
- **Sensori SMS**: Conteggio, ultimo messaggio, target disponibili
- **Servizi SMS**: Lettura, marcatura come letto, eliminazione
- **Eventi custom**: Automazioni avanzate per SMS ricevuti

### 📞 Funzionalità Chiamate
- **Servizi chiamata**: Composizione numero, riagganciare, recupero cronologia
- **Sensore chiamate**: Monitoraggio chiamate attive in tempo reale
- **Eventi chiamata**: Notifiche su azioni di chiamata

### 🛠️ Miglioramenti Tecnici
- **Libreria interna**: Nessuna dipendenza esterna, completamente autosufficiente
- **Async-safe**: Operazioni non bloccanti per l'interfaccia utente
- **Naming consistente**: Prefisso `fritzsms_` per tutti i sensori
- **Gestione errori robusta**: Fallback automatici e logging dettagliato

## 🔧 Installazione

1. **Copiare i file** in `/config/custom_components/fritz_automation/`
2. **Riavviare** Home Assistant
3. **Aggiungere integrazione** da Dispositivi e Servizi > Aggiungi Integrazione
4. **Inserire credenziali** del FRITZ!Box

## 📊 Utilizzo

### Sensori Disponibili
- `sensor.fritzsms_sms_count` - Numero totale SMS
- `sensor.fritzsms_last_sms` - Dettagli ultimo SMS  
- `sensor.fritzsms_sms_targets` - Target SMS disponibili
- `sensor.fritzsms_call_status` - Stato chiamate attive

### Servizi
- `fritz_automation.get_sms` - Recupera SMS
- `fritz_automation.mark_sms_read` - Marca SMS come letto
- `fritz_automation.delete_sms` - Elimina SMS
- `fritz_automation.make_call` - Effettua chiamata (modelli compatibili)
- `fritz_automation.hangup_call` - Termina chiamata
- `fritz_automation.get_calls` - Recupera cronologia chiamate

### Esempio Automazione
```yaml
automation:
  - alias: "Notifica SMS"
    trigger:
      platform: event
      event_type: fritzsms_sms_received
    action:
      - service: notify.mobile_app_phone
        data:
          message: "SMS da {{ trigger.event.data.sms_list[0].sender }}"
```

## ⚠️ Compatibilità

- **SMS**: Supportati su tutti i modelli FRITZ!Box con modem cellulare
- **Chiamate**: Disponibili solo su modelli con supporto telefonico (non LTE-only)
- **Home Assistant**: Versione 2024.1.0 o successiva

## 📚 Documentazione

- **GUIDE.md**: Guida completa con esempi
- **CHANGELOG.md**: Cronologia delle modifiche
- **services.yaml**: Definizioni complete dei servizi

## 🔄 Aggiornamenti

Integrazione indipendente - per aggiornamenti sostituire i file e riavviare Home Assistant.
