# Fritz Automation

Integrazione custom per Home Assistant per FRITZ!Box, completamente indipendente da HACS.

## 🆕 Caratteristiche Principali

### Sensori Disponibili
- **`sensor.fritz_automation_sms_count`** - Conta il numero totale di SMS
- **`sensor.fritz_automation_last_sms`** - Mostra i dettagli dell'ultimo SMS ricevuto  
- **`sensor.fritz_automation_sms_targets`** - Elenca i target SMS disponibili
- **`sensor.fritz_automation_call_status`** - Stato delle chiamate attive (per modelli supportati)

### Servizi SMS
- **`fritz_automation.get_sms`** - Recupera gli SMS e emette evento custom
- **`fritz_automation.mark_sms_read`** - Marca un SMS come letto
- **`fritz_automation.delete_sms`** - Elimina un SMS

### Servizi Chiamate (solo modelli compatibili)
- **`fritz_automation.make_call`** - Effettua una chiamata
- **`fritz_automation.hangup`** - Riaggancia la chiamata attiva
- **`fritz_automation.get_calls`** - Recupera la lista delle chiamate

### Eventi Custom
- **`fritz_automation_sms_received`** - Evento emesso quando vengono recuperati SMS
- **`fritz_automation_call_event`** - Evento emesso per azioni di chiamata

## 🔧 Installazione

1. **Fermare Home Assistant**

2. **Copiare i file** nella directory custom_components:
   ```
   /config/custom_components/fritz_automation/
   ```

3. **Riavviare Home Assistant**

4. **Configurare l'integrazione**:
   - Andare in Impostazioni > Dispositivi e Servizi
   - Cliccare "Aggiungi Integrazione"
   - Cercare "Fritz Automation"
   - Inserire credenziali del FRITZ!Box

## 📊 Utilizzo dei Sensori

### Esempio Automazione - Notifica Nuovo SMS
```yaml
automation:
  - alias: "Notifica SMS Ricevuto"
    trigger:
      platform: state
      entity_id: sensor.fritz_automation_sms_count
    condition:
      template: "{{ trigger.to_state.state|int > trigger.from_state.state|int }}"
    action:
      - service: notify.mobile_app_your_phone
        data:
          message: "Nuovo SMS: {{ state_attr('sensor.fritz_automation_last_sms', 'message') }}"
          title: "SMS da {{ state_attr('sensor.fritz_automation_last_sms', 'sender') }}"
```

## 🛠️ Utilizzo dei Servizi Custom

### Recuperare SMS
```yaml
# Script per recuperare ultimi 5 SMS
script:
  get_recent_sms:
    sequence:
      - service: fritz_automation.get_sms
        data:
          limit: 5
```

### Gestire SMS Specifico
```yaml
# Script per gestire SMS per ID
script:
  manage_sms:
    fields:
      sms_id:
        description: "ID dell'SMS da gestire"
        example: "12345"
      action:
        description: "Azione da eseguire"
        selector:
          select:
            options:
              - "read"
              - "delete"
    sequence:
      - choose:
          - conditions:
              - condition: template
                value_template: "{{ action == 'read' }}"
            sequence:
              - service: fritz_automation.mark_sms_read
                data:
                  sms_id: "{{ sms_id }}"
          - conditions:
              - condition: template
                value_template: "{{ action == 'delete' }}"
            sequence:
              - service: fritz_automation.delete_sms
                data:
                  sms_id: "{{ sms_id }}"
```

## ⚡ Eventi Custom

### Automazione con Eventi
```yaml
automation:
  - alias: "Processa SMS via Evento"
    trigger:
      platform: event
      event_type: fritz_automation_sms_received
    action:
      - service: script.process_sms_list
        data:
          sms_count: "{{ trigger.event.data.sms_count }}"
          sms_list: "{{ trigger.event.data.sms_list }}"

script:
  process_sms_list:
    fields:
      sms_count:
        description: "Numero di SMS ricevuti"
      sms_list:
        description: "Lista degli SMS"
    sequence:
      - repeat:
          count: "{{ sms_count }}"
          sequence:
            - variables:
                current_sms: "{{ sms_list[repeat.index - 1] }}"
            - service: notify.persistent_notification
              data:
                message: |
                  SMS da: {{ current_sms.sender }}
                  Data: {{ current_sms.date }}
                  Messaggio: {{ current_sms.message }}
                title: "SMS {{ repeat.index }} di {{ sms_count }}"
```

## 🔄 Integrazione con Node-RED

### Nodo per Monitoraggio SMS
```json
[
    {
        "id": "sms_monitor",
        "type": "server-events",
        "z": "flow_id",
        "name": "SMS Events",
        "event_type": "fritz_automation_sms_received",
        "exposeToHomeAssistant": false,
        "outputs": 1
    },
    {
        "id": "sms_processor",
        "type": "function",
        "z": "flow_id",
        "name": "Process SMS",
        "func": "const smsData = msg.payload.event;\nconst smsCount = smsData.sms_count;\nconst smsList = smsData.sms_list;\n\n// Processa ogni SMS\nfor (let i = 0; i < smsCount; i++) {\n    const sms = smsList[i];\n    node.send({\n        payload: {\n            sender: sms.sender,\n            message: sms.message,\n            date: sms.date,\n            id: sms.id\n        }\n    });\n}\n\nreturn null;",
        "outputs": 1
    }
]
```

## 🐛 Risoluzione Problemi

### Entità Obsolete
Se restano entità con nomi vecchi, rimuovere e riaggiungere l'integrazione da Dispositivi e Servizi.

### Debug
```yaml
# configuration.yaml
logger:
  logs:
    custom_components.fritz_automation: debug
```

### Servizi di Chiamata Non Disponibili
Se i servizi di chiamata non funzionano, il vostro modello FRITZ!Box potrebbe non supportare le funzionalità telefoniche.

## ⚠️ Note Importanti

- **Compatibilità**: Non tutti i modelli FRITZ!Box supportano le chiamate (es. 6890 LTE)
- **Parametri**: Alcuni parametri nei servizi di chiamata sono ignorati per compatibilità
- **Eventi**: Tutti i servizi emettono eventi custom per automazioni avanzate

# Verificare nei log la chiamata e l'evento emesso
```

## 📞 Utilizzo dei Servizi Chiamate

**Nota**: I servizi di chiamata sono disponibili solo su modelli FRITZ!Box che supportano la funzionalità telefonica (non tutti i modelli LTE).

### Effettuare una Chiamata
```yaml
script:
  emergency_call:
    sequence:
      - service: fritz_automation.dial
        data:
          number: "+39123456789"
```

### Controllare Chiamate Attive
```yaml
automation:
  - alias: "Monitor Chiamate Attive"
    trigger:
      platform: time_pattern
      minutes: "/1"
    action:
      - service: fritz_automation.get_calls
      - condition: template
        value_template: "{{ state_attr('sensor.fritz_automation_call_status', 'active_calls') | int > 0 }}"
      - service: notify.mobile_app_phone
        data:
          message: "Chiamata in corso: {{ states('sensor.fritz_automation_call_status') }}"
```

### Riagganciare Automaticamente
```yaml
script:
  auto_hangup:
    sequence:
      - service: fritz_automation.hangup
      - service: notify.persistent_notification
        data:
          message: "Chiamata terminata automaticamente"

## 📱 Esempi di Utilizzo

### Dashboard Lovelace
```yaml
type: entities
title: "Fritz Automation"
entities:
  - sensor.fritz_automation_sms_count
  - sensor.fritz_automation_last_sms
  - sensor.fritz_automation_call_status
```

### Node-RED - Monitoraggio Eventi
```json
{
    "id": "sms_monitor",
    "type": "server-events", 
    "event_type": "fritz_automation_sms_received",
    "outputs": 1
}
```

## 🔄 Aggiornamenti

Integrazione indipendente da HACS. Per aggiornamenti sostituire i file in `custom_components/fritz_automation/` e riavviare Home Assistant.

Per problemi o suggerimenti, controllare i log di Home Assistant con debug abilitato e documentare:
- Versione di Home Assistant
- Modello FRITZ!Box  
- Log degli errori completi
- Configurazione utilizzata
