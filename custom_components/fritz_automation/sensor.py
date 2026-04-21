"""AVM FRITZ!Box Automation sensor platform."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, TYPE_CHECKING

from fritzconnection import FritzConnection
from fritzconnection.lib.fritzcall import FritzCall
# Import FritzBox from the correct relative path (single dot)
from .fritzbox import FritzBox
from aiohttp import ClientSession

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, CONF_HOST
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DOMAIN

if TYPE_CHECKING:
    from . import FritzBoxConfigEntry

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=2)
CALL_SCAN_INTERVAL_NORMAL = timedelta(seconds=30)  # Intervallo normale per le chiamate
CALL_SCAN_INTERVAL_ACTIVE = timedelta(seconds=5)   # Intervallo durante chiamate attive

CALL_MONITOR_AFTER_SECONDS = 5                    # Continua monitoraggio rapido per 60 sec dopo fine chiamata

# --- Real-time Call Monitor (porta 1012) ---
class FritzBoxRealtimeCallMonitor:
    """Gestisce la connessione socket in tempo reale al call monitor della FRITZ!Box (porta 1012)."""
    def __init__(self, hass: HomeAssistant, host: str, on_event_callback=None):
        self.hass = hass
        self.host = host
        self.port = 1012
        self._task = None
        self._stopped = False
        self._on_event_callback = on_event_callback  # funzione chiamata per ogni evento
        self._last_event = None

    def start(self):
        """Avvia la connessione in background."""
        if not self._task:
            self._stopped = False
            self._task = self.hass.loop.create_task(self._run())

    def stop(self):
        """Ferma la connessione."""
        self._stopped = True
        if self._task:
            self._task.cancel()
            self._task = None

    async def _run(self):
        import socket
        _LOGGER.info("[RealtimeCallMonitor] Connessione a %s:%d", self.host, self.port)
        while not self._stopped:
            try:
                reader, writer = await asyncio.open_connection(self.host, self.port)
                _LOGGER.info("[RealtimeCallMonitor] Connesso a %s:%d", self.host, self.port)
                while not self._stopped:
                    line = await reader.readline()
                    if not line:
                        _LOGGER.warning("[RealtimeCallMonitor] Connessione chiusa dal FritzBox")
                        break
                    try:
                        decoded = line.decode("utf-8").strip()
                        if decoded:
                            _LOGGER.debug("[RealtimeCallMonitor] Evento: %s", decoded)
                            self._last_event = decoded
                            if self._on_event_callback:
                                await self._on_event_callback(decoded)
                    except Exception as err:
                        _LOGGER.error("[RealtimeCallMonitor] Errore decodifica evento: %s", err)
            except Exception as err:
                _LOGGER.error("[RealtimeCallMonitor] Errore connessione: %s", err)
                await asyncio.sleep(10)

    def get_last_event(self):
        return self._last_event
class FritzBoxCallMonitorEventParser:
    """Parser per le righe del call monitor (porta 1012)."""
    @staticmethod
    def parse(line: str) -> dict | None:
        # Esempi di linee:
        # 21.07.23 18:00:00;RING;0;0123456789;123456;SIP0;
        # 21.07.23 18:00:05;CALL;1;123456;0123456789;SIP1;
        # 21.07.23 18:00:10;CONNECT;1;123456;0123456789;SIP1;
        # 21.07.23 18:00:20;DISCONNECT;1;0;
        try:
            parts = line.split(";")
            if len(parts) < 2:
                return None
            event_type = parts[1]
            data = {"raw": line, "event_type": event_type}
            # Helper per device: se mancante o vuoto, None
            def get_device(idx):
                if len(parts) > idx and parts[idx].strip():
                    return parts[idx].strip()
                return None
            if event_type == "RING":
                data.update({
                    "date": parts[0],
                    "call_type": "inbound",
                    "external_number": parts[3] if len(parts) > 3 else None,
                    "internal_number": parts[4] if len(parts) > 4 else None,
                    "device": get_device(5),
                })
            elif event_type == "CALL":
                data.update({
                    "date": parts[0],
                    "call_type": "outbound",
                    "internal_number": parts[3] if len(parts) > 3 else None,
                    "external_number": parts[4] if len(parts) > 4 else None,
                    "device": get_device(5),
                })
            elif event_type == "CONNECT":
                data.update({
                    "date": parts[0],
                    "connection_id": parts[2] if len(parts) > 2 else None,
                    "internal_number": parts[3] if len(parts) > 3 else None,
                    "external_number": parts[4] if len(parts) > 4 else None,
                    "device": get_device(5),
                })
            elif event_type == "DISCONNECT":
                data.update({
                    "date": parts[0],
                    "connection_id": parts[2] if len(parts) > 2 else None,
                    "duration": parts[3] if len(parts) > 3 else None,
                })
            return data
        except Exception as err:
            _LOGGER.error("[CallMonitorEventParser] Errore parsing: %s", err)
            return None
class FritzBoxCallMonitorRealtimeManager:
    """Gestisce la logica di alto livello per il call monitor in tempo reale."""
    def __init__(self, hass: HomeAssistant, host: str):
        self.hass = hass
        self.host = host
        self.monitor = FritzBoxRealtimeCallMonitor(hass, host, self._on_event)
        self._event_history = []  # lista di dict
        self._last_state = None
        self._active_calls = {}
        self._last_disconnect = None
        self._started = False

    def start(self):
        if not self._started:
            self.monitor.start()
            self._started = True
            _LOGGER.info("[CallMonitorRealtimeManager] Avviato monitor realtime su %s", self.host)

    def stop(self):
        if self._started:
            self.monitor.stop()
            self._started = False
            _LOGGER.info("[CallMonitorRealtimeManager] Fermato monitor realtime su %s", self.host)

    async def _on_event(self, line: str):
        _LOGGER.warning("[CallMonitorRealtimeManager] Ricevuto evento: %s", line)
        event = FritzBoxCallMonitorEventParser.parse(line)
        if not event:
            return
        self._event_history.append(event)
        # Mantieni solo gli ultimi 50 eventi
        self._event_history = self._event_history[-50:]
        # Logica base: aggiorna stato attivo
        if event["event_type"] in ("RING", "CALL"):
            self._active_calls[event.get("connection_id", event.get("external_number", "?"))] = event
        elif event["event_type"] == "DISCONNECT":
            self._last_disconnect = event
            # Rimuovi dalla lista attivi
            conn_id = event.get("connection_id")
            if conn_id and conn_id in self._active_calls:
                del self._active_calls[conn_id]

        # --- LOGICA HANGUP DECT (solo device 'borgogrotta') ---
        # Se evento CALL (chiamata in uscita) o DISCONNECT, controlla se serve hangup
        if event["event_type"] == "CALL":
            # Salva info per uso successivo
            self._last_outbound_call = event
        if event["event_type"] == "DISCONNECT":
            # Logga dettagli evento e detection
            _LOGGER.warning("[CallMonitorRealtimeManager][DEBUG] Evento DISCONNECT: %s", event)
            last_call = getattr(self, "_last_outbound_call", None)
            if last_call:
                _LOGGER.warning("[CallMonitorRealtimeManager][DEBUG] Ultima chiamata outbound: %s", last_call)
                device = (last_call.get("device") or "").strip().lower() if last_call.get("device") is not None else ""
                internal_number = str(last_call.get("internal_number") or "")
                is_dect = False
                # Solo device whitelist: 'borgogrotta' (case-insensitive)
                # Whitelist: nome e numero specifico (case-insensitive per nome)
                whitelist = ["borgogrotta", "3427453719"]
                if device and any(device == w.lower() for w in whitelist):
                    is_dect = True
                    _LOGGER.warning("[CallMonitorRealtimeManager][DECT DETECTION] device '%s' in whitelist DECT (case-insensitive, numeri inclusi)", device)
                else:
                    _LOGGER.debug("[CallMonitorRealtimeManager][DECT DETECTION] device '%s' NON in whitelist DECT (case-insensitive, numeri inclusi)", device)
                if is_dect:
                    call_conn_id = last_call.get("connection_id", last_call.get("external_number", "?"))
                    # Cerca CONNECT con stesso conn_id dopo CALL
                    found_connect = False
                    for e in reversed(self._event_history):
                        if e.get("event_type") == "CONNECT" and e.get("connection_id") == call_conn_id:
                            found_connect = True
                            break
                        if e is last_call:
                            break
                    disconnect_duration = event.get("duration")
                    try:
                        duration_sec = int(disconnect_duration) if disconnect_duration is not None else 0
                    except Exception:
                        duration_sec = 0
                    _LOGGER.warning("[CallMonitorRealtimeManager][DEBUG] found_connect=%s, duration_sec=%s", found_connect, duration_sec)
                    # Forza hangup anche se c'è CONNECT ma la durata è nulla o molto breve
                    if (not found_connect) or (duration_sec == 0 or duration_sec < 2):
                        _LOGGER.warning("[CallMonitorRealtimeManager] Rilevata chiamata in uscita non risposta/rifiutata DECT (device in whitelist, no CONNECT o durata nulla/breve): provo hangup!")
                        await self._hangup_dect_call()
                self._last_outbound_call = None

        # Emetti evento su Home Assistant
        self.hass.bus.async_fire(f"{DOMAIN}_callmonitor_event", event)
        _LOGGER.info("[CallMonitorRealtimeManager] Evento callmonitor: %s", event)

    async def _hangup_dect_call(self):
        _LOGGER.warning("[CallMonitorRealtimeManager] Chiamata _hangup_dect_call()")
        """Invia comando hangup al FritzBox usando la stessa istanza e credenziali usate per SMS (entry.runtime_data)."""
        config_entries = getattr(self.hass, "config_entries", None)
        if not config_entries:
            _LOGGER.error("[CallMonitorRealtimeManager] Impossibile recuperare config_entries per hangup.")
            return
        entry = None
        for e in config_entries.async_entries(DOMAIN):
            if e.data.get("host") == self.host:
                entry = e
                break
        if not entry:
            _LOGGER.error("[CallMonitorRealtimeManager] Nessuna config_entry trovata per host %s", self.host)
            return
        # Usa la stessa istanza usata per SMS (runtime_data)
        box = getattr(entry, "runtime_data", None)
        if not box:
            _LOGGER.error("[CallMonitorRealtimeManager] Nessuna istanza box (runtime_data) trovata nella config_entry per host %s", self.host)
            return
        username = entry.data.get("username") or entry.data.get("user")
        password = entry.data.get("password")
        if not username or not password:
            _LOGGER.error("[CallMonitorRealtimeManager] Credenziali mancanti per hangup.")
            return
        try:
            ok = await box.hangup_call(username, password)
            if not ok:
                _LOGGER.error("[CallMonitorRealtimeManager] Errore nell'invio comando hangup DECT! (hangup_call ha restituito False)")
        except Exception as ex:
            _LOGGER.error(f"[CallMonitorRealtimeManager] Eccezione hangup DECT: {ex}")

    def get_state(self):
        """Restituisce lo stato attuale (chiamate attive, ultimi eventi)."""
        return {
            "active_calls": list(self._active_calls.values()),
            "event_history": self._event_history,
            "last_disconnect": self._last_disconnect,
        }
realtime_callmonitor_manager: FritzBoxCallMonitorRealtimeManager | None = None

SENSOR_TYPES: tuple[SensorEntityDescription, ...] = (
    SensorEntityDescription(
        key="sms_count",
        name="SMS Count",
        icon="mdi:message-text-outline",
        native_unit_of_measurement="messages",
    ),
    SensorEntityDescription(
        key="last_sms",
        name="Last SMS",
        icon="mdi:message-text",
    ),
    SensorEntityDescription(
        key="sms_targets",
        name="SMS Targets",
        icon="mdi:message-alert",
    ),
    SensorEntityDescription(
        key="call_status",
        name="Call Status",
        icon="mdi:phone",
    ),
)


def _create_fritz_connection_for_calls(host: str, username: str, password: str) -> FritzConnection:
    """Create FritzConnection synchronously for call status (for use in executor)."""
    return FritzConnection(
        address=host,
        user=username,
        password=password
    )


def _get_calls_status_sync(fritz_conn: FritzConnection) -> dict:
    """Get call status synchronously (for use in executor)."""
    try:
        fritz_call = FritzCall(fritz_conn)
        
        # Usa l'API ufficiale di FritzCall
        _LOGGER.info("Using FritzCall.get_calls() for sensor")
        call_list = fritz_call.get_calls()
        
        # Processa le chiamate usando gli attributi dell'oggetto Call
        processed_calls = []
        active_calls = []
        
        for call in call_list:
            # Converti oggetto Call in dizionario
            call_info = {
                "id": call.id,  # int
                "type": call.type,  # int  
                "Called": call.Called,
                "Caller": call.Caller,
                "CallerNumber": call.CallerNumber,
                "CalledNumber": call.CalledNumber,
                "Name": call.Name,
                "Device": call.Device,
                "Port": call.Port,
                "Date": call.Date,  # String originale
                "Duration": call.Duration,  # String originale
                "Count": call.Count,
                # "Path": call.Path,  # Non sempre presente
                "Path": getattr(call, "Path", getattr(call, "path", None)),
                "date": call.date.isoformat() if hasattr(call, "date") and call.date else None,  # datetime convertito
                "duration_seconds": call.duration.total_seconds() if hasattr(call, "duration") and call.duration else None,  # timedelta convertito
            }
            
            processed_calls.append(call_info)
            
            # Determina chiamate attive basandosi sui tipi di chiamata
            # ACTIVE_RECEIVED_CALL_TYPE = 9, ACTIVE_OUT_CALL_TYPE = 11
            if call.type in [9, 11]:  # Chiamate attive
                active_calls.append(call_info)
        
        _LOGGER.info("Sensor processed %d calls, %d active", len(processed_calls), len(active_calls))
        
        return {
            "call_list": processed_calls,
            "active_calls": active_calls,
            "last_call": processed_calls[0] if processed_calls else None,
            "call_history": processed_calls[:10] if processed_calls else []
        }
        
    except Exception as err:
        _LOGGER.error("Error getting call status: %s", err, exc_info=True)
        return {
            "call_list": [],
            "active_calls": [],
            "last_call": None,
            "call_history": []
        }


class FritzBoxSMSUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching SMS data from FRITZ!Box."""

    def __init__(self, hass: HomeAssistant, entry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_sms",
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch SMS data from FRITZ!Box."""
        box = self.entry.runtime_data
        cfg = self.entry.data

        try:
            await box.login(cfg[CONF_USERNAME], cfg[CONF_PASSWORD])
            
            sms_list = []
            sms_count = 0
            last_sms = None
            
            try:
                # Prova diversi metodi per ottenere gli SMS
                if hasattr(box, 'get_sms_list'):
                    sms_list = await box.get_sms_list()
                elif hasattr(box, 'list_sms'):
                    sms_list = await box.list_sms()
                elif hasattr(box, 'get_messages'):
                    sms_list = await box.get_messages()
                    
                if sms_list:
                    sms_count = len(sms_list)
                    if isinstance(sms_list, list) and sms_list:
                        last_sms = sms_list[-1]
                        _LOGGER.debug("SMS structure: %s", last_sms)
                        
            except (AttributeError, Exception) as err:
                _LOGGER.debug("SMS reading not available: %s", err)
                
            await box.logout()
            
            return {
                "sms_count": sms_count,
                "last_sms": last_sms,
                "sms_list": sms_list,
            }
            
        except Exception as err:
            await box.logout()
            raise UpdateFailed(f"Error communicating with FRITZ!Box: {err}") from err


class FritzBoxCallUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching call data from FRITZ!Box with dynamic frequency."""

    def __init__(self, hass: HomeAssistant, config_entry) -> None:
        """Initialize the call coordinator."""
        self.config_entry = config_entry
        self._fritz_conn = None
        self._last_active_time = None
        self._is_in_active_mode = False
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_calls",
            update_interval=CALL_SCAN_INTERVAL_NORMAL,  # Inizia con intervallo normale
        )

    def _should_use_active_mode(self, call_data: dict) -> bool:
        """Determine if we should use active monitoring mode."""
        active_calls = call_data.get("active_calls", [])
        has_active_calls = len(active_calls) > 0
        
        # Se ci sono chiamate attive, attiva modo rapido
        if has_active_calls:
            self._last_active_time = datetime.now()
            return True
        
        # Se non ci sono chiamate attive ma eravamo in modo rapido,
        # continua per altri 60 secondi
        if self._last_active_time:
            time_since_last_active = datetime.now() - self._last_active_time
            if time_since_last_active.total_seconds() < CALL_MONITOR_AFTER_SECONDS:
                return True
            else:
                # Reset timer
                self._last_active_time = None
                return False
        
        return False

    def _update_scan_interval(self, should_be_active: bool) -> None:
        """Update scan interval based on call activity."""
        new_interval = CALL_SCAN_INTERVAL_ACTIVE if should_be_active else CALL_SCAN_INTERVAL_NORMAL
        
        # Aggiorna solo se cambiato
        if self.update_interval != new_interval:
            old_interval = self.update_interval.total_seconds()
            self.update_interval = new_interval
            self._is_in_active_mode = should_be_active
            
            mode = "ACTIVE" if should_be_active else "NORMAL"
            _LOGGER.info("Call monitoring mode changed to %s: %ds → %ds", 
                        mode, old_interval, new_interval.total_seconds())

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch call data from FRITZ!Box."""
        try:
            # Crea connessione se non esiste
            if self._fritz_conn is None:
                self._fritz_conn = await self.hass.async_add_executor_job(
                    _create_fritz_connection_for_calls,
                    self.config_entry.data[CONF_HOST],
                    self.config_entry.data[CONF_USERNAME],
                    self.config_entry.data[CONF_PASSWORD]
                )
            
            # Ottieni lo stato delle chiamate
            call_status = await self.hass.async_add_executor_job(
                _get_calls_status_sync,
                self._fritz_conn
            )
            
            # Determina se usare modo attivo
            should_be_active = self._should_use_active_mode(call_status)
            self._update_scan_interval(should_be_active)
            
            # Aggiungi info modalità ai dati
            call_status["monitoring_mode"] = "active" if self._is_in_active_mode else "normal"
            call_status["update_interval_seconds"] = self.update_interval.total_seconds()
            call_status["last_active_time"] = self._last_active_time.isoformat() if self._last_active_time else None
            
            return call_status
            
        except Exception as err:
            # Reset della connessione in caso di errore
            self._fritz_conn = None
            raise UpdateFailed(f"Error communicating with FRITZ!Box: {err}") from err


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the FRITZ!Box Automation sensors from a config entry."""
    

    # --- Avvia il call monitor realtime ---
    global realtime_callmonitor_manager
    host = config_entry.data.get("host")
    if not host:
        _LOGGER.error("[async_setup_entry] Host FritzBox non specificato!")
        return
    realtime_callmonitor_manager = FritzBoxCallMonitorRealtimeManager(hass, host)
    realtime_callmonitor_manager.start()

    # Coordinatore per SMS (aggiornamento lento)
    sms_coordinator = FritzBoxSMSUpdateCoordinator(hass, config_entry)
    await sms_coordinator.async_config_entry_first_refresh()

    # Coordinatore per chiamate (polling tradizionale)
    call_coordinator = FritzBoxCallUpdateCoordinator(hass, config_entry)
    await call_coordinator.async_config_entry_first_refresh()

    entities = []

    # Crea i sensori SMS e chiamate
    for description in SENSOR_TYPES:
        if description.key in ["sms_count", "last_sms"]:
            entities.append(FritzBoxSMSSensor(sms_coordinator, config_entry, description))
        elif description.key == "sms_targets":
            entities.append(FritzBoxSMSTargetsSensor(hass, config_entry))
        elif description.key == "call_status":
            # Passa anche il manager realtime al sensore chiamate
            entities.append(FritzBoxCallStatusSensor(call_coordinator, config_entry, description, realtime_manager=realtime_callmonitor_manager))

    async_add_entities(entities)


class FritzBoxSMSSensor(CoordinatorEntity, SensorEntity):
    """Representation of a FRITZ!Box SMS sensor."""

    def __init__(
        self,
        coordinator: FritzBoxSMSUpdateCoordinator,
        config_entry,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_{description.key}"
        
        # Nomi delle entità compatibili
        if description.key == "last_sms":
            self._attr_name = "Fritz Automation Last SMS"
            # Forza l'entity_id per compatibilità
            self.entity_id = "sensor.fritz_automation_last_sms"
        elif description.key == "sms_count":
            self._attr_name = "Fritz Automation SMS Count"
            self.entity_id = "sensor.fritz_automation_sms_count"
        else:
            self._attr_name = f"Fritz Automation {description.name}"
            
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name="Fritz Automation",
            configuration_url=f"http://{config_entry.data['host']}/",
        )

    @property
    def native_value(self) -> str | int | None:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None
            
        if self.entity_description.key == "sms_count":
            return self.coordinator.data.get("sms_count", 0)
            
        elif self.entity_description.key == "last_sms":
            last_sms = self.coordinator.data.get("last_sms")
            if not last_sms:
                return "No SMS"
                
            try:
                if isinstance(last_sms, dict):
                    # Estrai i campi principali
                    sender = (last_sms.get("sender") or 
                             last_sms.get("from") or 
                             last_sms.get("number") or "Unknown")
                    message = (last_sms.get("message") or 
                              last_sms.get("text") or 
                              last_sms.get("content") or "")
                    timestamp = (last_sms.get("timestamp") or 
                                last_sms.get("date") or "")
                    
                    if message:
                        return f"From: {sender} - {message[:50]}{'...' if len(message) > 50 else ''}"
                    else:
                        return f"From: {sender} ({timestamp})"
                else:
                    return str(last_sms)
            except Exception as err:
                _LOGGER.warning("Error processing last SMS: %s", err)
                return "Error processing SMS"
        
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        if not self.coordinator.data:
            return None
            
        attrs = {}
        
        if self.entity_description.key == "last_sms":
            last_sms = self.coordinator.data.get("last_sms")
            if last_sms and isinstance(last_sms, dict):
                attrs.update({
                    "sender": last_sms.get("sender") or last_sms.get("from"),
                    "message": last_sms.get("message") or last_sms.get("text"),
                    "timestamp": last_sms.get("timestamp") or last_sms.get("date"),
                    "raw_data": last_sms,
                })
        elif self.entity_description.key == "sms_count":
            attrs["last_update"] = datetime.now().isoformat()
            if self.coordinator.data.get("sms_list"):
                attrs["total_sms"] = len(self.coordinator.data["sms_list"])
            
        return attrs if attrs else None


class FritzBoxSMSTargetsSensor(SensorEntity):
    """Sensor that shows configured SMS targets."""

    def __init__(self, hass: HomeAssistant, config_entry) -> None:
        """Initialize the targets sensor."""
        self.hass = hass
        self._config_entry = config_entry
        self._attr_unique_id = f"{config_entry.entry_id}_sms_targets"
        self._attr_name = "Fritz Automation SMS Targets"
        self._attr_icon = "mdi:message-alert"
        # Mantieni la coerenza con gli altri sensori
        self.entity_id = "sensor.fritz_automation_sms_targets"
        
        self._attr_device_info = dr.DeviceInfo(
            identifiers={(DOMAIN, config_entry.entry_id)},
            name="Fritz Automation",
            configuration_url=f"http://{config_entry.data['host']}/",
        )

    @property
    def native_value(self) -> str:
        """Return the state of the sensor."""
        subentries = self._config_entry.as_dict().get("subentries", {})
        
        if not subentries:
            return "No targets configured"

        targets = []
        
        # Gestisci sia liste che dizionari
        if isinstance(subentries, dict):
            for subentry in subentries.values():
                target = subentry.get("data", {}).get("target", "Unknown")
                targets.append(target)
        elif isinstance(subentries, list):
            for subentry in subentries:
                if isinstance(subentry, dict):
                    target = subentry.get("data", {}).get("target", "Unknown")
                    targets.append(target)

        return ", ".join(targets) if targets else "No targets"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return additional state attributes."""
        subentries = self._config_entry.as_dict().get("subentries", {})
        
        if not subentries:
            return {"targets": [], "total_targets": 0}
        
        # Ottieni il registry delle entità per trovare gli ID delle notify entities
        entity_registry = er.async_get(self.hass)
        notify_entities = [
            e for e in entity_registry.entities.values()
            if e.platform == DOMAIN and e.domain == "notify"
        ]
        
        targets_info = []
        
        # Gestisci sia liste che dizionari
        if isinstance(subentries, dict):
            for subentry_id, subentry in subentries.items():
                data = subentry.get("data", {})
                name = data.get("name", "Unknown")
                target = data.get("target", "Unknown")
                
                # Trova l'entity_id corrispondente usando original_name
                notify_id = None
                for ent in notify_entities:
                    if ent.original_name == name:
                        notify_id = ent.entity_id
                        break
                
                targets_info.append({
                    "name": name,
                    "target": target,
                    "notify_id": notify_id or "unknown",
                    "id": subentry_id
                })
        elif isinstance(subentries, list):
            for idx, subentry in enumerate(subentries):
                if isinstance(subentry, dict):
                    data = subentry.get("data", {})
                    name = data.get("name", "Unknown")
                    target = data.get("target", "Unknown")
                    
                    # Trova l'entity_id corrispondente usando original_name
                    notify_id = None
                    for ent in notify_entities:
                        if ent.original_name == name:
                            notify_id = ent.entity_id
                            break
                    
                    targets_info.append({
                        "name": name,
                        "target": target,
                        "notify_id": notify_id or "unknown",
                        "id": f"subentry_{idx}"
                    })

        return {
            "targets": targets_info,
            "total_targets": len(targets_info)
        }



class FritzBoxCallStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensore stato chiamate FRITZ!Box con polling e monitor realtime."""

    def __init__(self, coordinator: FritzBoxCallUpdateCoordinator,
                 config_entry: ConfigEntry,
                 description: SensorEntityDescription,
                 realtime_manager: FritzBoxCallMonitorRealtimeManager = None) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._config_entry = config_entry
        self._attr_name = f"Fritz Automation {description.name}"
        self._attr_unique_id = f"{config_entry.entry_id}_{description.key}"
        self.entity_id = "sensor.fritz_automation_call_status"

        self._attr_device_info = {
            "identifiers": {(DOMAIN, "fritz_automation")},
            "name": "Fritz Automation",
            "manufacturer": "AVM",
            "model": "Fritz Automation Integration",
        }

        # Stato precedente per rilevare transizioni (polling)
        self._previous_calls = {}
        self._recently_ended_calls = {}
        self._answered_calls = []
        self._last_answer_detection = None
        self._call_state_history = {}

        # Realtime call monitor manager
        self._realtime_manager = realtime_manager

        # Listener polling
        self.async_on_remove(
            coordinator.async_add_listener(self._handle_coordinator_update)
        )

    def _handle_coordinator_update(self) -> None:
        """Handle coordinator update and check for call answer transitions."""
        if not self.coordinator.data:
            return
        current_calls = self.coordinator.data.get("call_list", [])
        _LOGGER.debug("[DEBUG] _handle_coordinator_update called (entity_id=%s)", self.entity_id)
        _LOGGER.debug("[DEBUG] Current calls: %s (entity_id=%s)", current_calls, self.entity_id)
        self.hass.async_create_task(
            self._detect_call_answer_transitions(current_calls)
        )


    async def _detect_call_answer_transitions(self, current_calls: list) -> None:
        """Detect call answer transitions and emit events, even for quickly ended calls."""
        current_calls_by_id = {call["id"]: call for call in current_calls}

        # Aggiorna lo storico dei tipi per ogni chiamata attuale
        for call in current_calls:
            call_id = call["id"]
            call_type = call["type"]
            history = self._call_state_history.get(call_id, [])
            if not history or history[-1] != call_type:
                history.append(call_type)
                # Tieni solo gli ultimi 4 tipi
                history = history[-4:]
                self._call_state_history[call_id] = history
            _LOGGER.debug("[DEBUG] Call %s type history: %s (entity_id=%s)", call_id, history, self.entity_id)

        all_call_ids = set(current_calls_by_id.keys()) | set(self._recently_ended_calls.keys())
        _LOGGER.debug("[DEBUG] All call ids to process: %s (entity_id=%s)", all_call_ids, self.entity_id)
        _LOGGER.debug("[DEBUG] _previous_calls: %s (entity_id=%s)", self._previous_calls, self.entity_id)
        _LOGGER.debug("[DEBUG] _recently_ended_calls: %s (entity_id=%s)", self._recently_ended_calls, self.entity_id)
        _LOGGER.debug("[DEBUG] _call_state_history: %s (entity_id=%s)", self._call_state_history, self.entity_id)

        for call_id in all_call_ids:
            current_call = current_calls_by_id.get(call_id)
            previous_call = self._previous_calls.get(call_id)
            if current_call is None and call_id in self._recently_ended_calls:
                current_call = self._recently_ended_calls[call_id]

            if previous_call and current_call:
                answer_detected = self._check_answer_transition(previous_call, current_call)
                if answer_detected:
                    self._answered_calls.append({
                        "call_id": call_id,
                        "transition": answer_detected["transition"],
                        "answer_type": answer_detected["answer_type"],
                        "call_info": current_call,
                        "timestamp": datetime.now().isoformat()
                    })
                    self._answered_calls = self._answered_calls[-10:]
                    self._last_answer_detection = answer_detected
                    self.hass.bus.async_fire(
                        f"{DOMAIN}_call_answered",
                        {
                            "call_id": call_id,
                            "answer_type": answer_detected["answer_type"],
                            "transition": answer_detected["transition"],
                            "call_info": current_call,
                            "timestamp": datetime.now().isoformat()
                        }
                    )
                    _LOGGER.info("Call answer detected: %s for call %s", answer_detected["answer_type"], call_id)

        for call_id, prev_call in self._previous_calls.items():
            if call_id not in current_calls_by_id:
                history = self._call_state_history.get(call_id, [])
                detected = None
                if len(history) >= 2:
                    if history[-2:] == [9, 1]:
                        detected = {"transition": "9→1", "answer_type": "inbound_answered_instant"}
                    elif history[-2:] == [11, 3]:
                        detected = {"transition": "11→3", "answer_type": "outbound_answered_instant"}
                if len(history) >= 3:
                    if history[-3:] == [9, 1, 2]:
                        detected = {"transition": "9→1→2", "answer_type": "inbound_answered_then_missed"}
                    elif history[-3:] == [11, 3, 2]:
                        detected = {"transition": "11→3→2", "answer_type": "outbound_answered_then_no_answer"}

                current_call = prev_call
                duration = current_call.get("duration_seconds", 0) or 0
                confirmed = detected and detected["answer_type"].endswith("answered_instant") and duration > 0

                if detected:
                    if not any(x["call_id"] == call_id and x["transition"] == detected["transition"] for x in self._answered_calls):
                        event_data = {
                            "call_id": call_id,
                            "transition": detected["transition"],
                            "answer_type": detected["answer_type"] if confirmed else f'{detected["answer_type"]}_no_duration',
                            "duration": duration,
                            "confirmed": confirmed,
                            "call_info": current_call,
                            "timestamp": datetime.now().isoformat()
                        }
                        self._answered_calls.append(event_data)
                        self._answered_calls = self._answered_calls[-10:]
                        self._last_answer_detection = event_data
                        self.hass.bus.async_fire(
                            f"{DOMAIN}_call_answered",
                            event_data
                        )
                        _LOGGER.info("Call answer detected (history): %s for call %s", event_data["answer_type"], call_id)
                else:
                    answer_detected = self._check_answer_transition(prev_call, current_call)
                    if answer_detected:
                        if not any(x["call_id"] == call_id and x["transition"] == answer_detected["transition"] for x in self._answered_calls):
                            event_data = {
                                "call_id": call_id,
                                "transition": answer_detected["transition"],
                                "answer_type": answer_detected["answer_type"],
                                "duration": answer_detected.get("duration", 0),
                                "confirmed": answer_detected.get("confirmed", False),
                                "call_info": current_call,
                                "timestamp": datetime.now().isoformat()
                            }
                            self._answered_calls.append(event_data)
                            self._answered_calls = self._answered_calls[-10:]
                            self._last_answer_detection = event_data
                            self.hass.bus.async_fire(
                                f"{DOMAIN}_call_answered",
                                event_data
                            )
                            _LOGGER.info("Call answer detected (on end): %s for call %s", answer_detected["answer_type"], call_id)

        self._recently_ended_calls = {}
        for call_id, prev_call in self._previous_calls.items():
            if call_id not in current_calls_by_id:
                self._recently_ended_calls[call_id] = prev_call

        self._previous_calls = current_calls_by_id.copy()

        for call_id in list(self._call_state_history.keys()):
            if call_id not in current_calls_by_id and call_id not in self._recently_ended_calls:
                del self._call_state_history[call_id]

    def _check_answer_transition(self, previous_call: dict, current_call: dict) -> dict | None:
        """Check if a call transition indicates an answer."""
        prev_type = previous_call["type"]
        curr_type = current_call["type"]
        duration = current_call.get("duration_seconds", 0) or 0
        
        # Transizioni che indicano risposta
        answer_transitions = {
            (11, 3): "outbound_answered",    # Chiamata effettuata risposta
            (9, 1): "inbound_answered",      # Chiamata ricevuta risposta
            (9, 2): "inbound_missed",        # Chiamata ricevuta persa
            (9, 10): "inbound_rejected",     # Chiamata ricevuta rifiutata
            (11, 2): "outbound_no_answer",   # Chiamata effettuata senza risposta
        }
        
        transition_key = (prev_type, curr_type)
        
        if transition_key in answer_transitions:
            answer_type = answer_transitions[transition_key]
            
            # Valida la risposta in base alla durata
            if answer_type in ["outbound_answered", "inbound_answered"]:
                if duration > 0:
                    return {
                        "transition": f"{prev_type}→{curr_type}",
                        "answer_type": answer_type,
                        "duration": duration,
                        "confirmed": True
                    }
                else:
                    return {
                        "transition": f"{prev_type}→{curr_type}",
                        "answer_type": f"{answer_type}_no_duration",
                        "duration": duration,
                        "confirmed": False
                    }
            else:
                # Chiamate perse/rifiutate
                return {
                    "transition": f"{prev_type}→{curr_type}",
                    "answer_type": answer_type,
                    "duration": duration,
                    "confirmed": True
                }
        
        return None

    @property
    def native_value(self) -> str:
        """Stato: 'active' se chiamate attive (realtime o polling), altrimenti 'idle'."""
        # Priorità: realtime
        if self._realtime_manager:
            state = self._realtime_manager.get_state()
            if state["active_calls"]:
                return "active"
        # Fallback: polling
        if self.coordinator.data:
            active_calls = self.coordinator.data.get("active_calls", [])
            if active_calls:
                return "active"
        return "idle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Attributi: unisce info polling e realtime."""
        attrs = {}
        # Dati realtime
        if self._realtime_manager:
            state = self._realtime_manager.get_state()
            attrs["realtime_active_calls"] = state["active_calls"]
            attrs["realtime_event_history"] = state["event_history"]
            attrs["realtime_last_disconnect"] = state["last_disconnect"]
        # Dati polling
        if self.coordinator.data:
            attrs["active_calls"] = len(self.coordinator.data.get("active_calls", []))
            attrs["active_call_list"] = self.coordinator.data.get("active_calls", [])
            attrs["last_call"] = self.coordinator.data.get("last_call")
            attrs["call_history"] = self.coordinator.data.get("call_history", [])
            attrs["monitoring_mode"] = self.coordinator.data.get("monitoring_mode", "normal")
            attrs["update_interval_seconds"] = self.coordinator.data.get("update_interval_seconds", 30)
            attrs["last_active_time"] = self.coordinator.data.get("last_active_time")
        # Rilevamento risposta (polling)
        attrs["answered_calls"] = len(self._answered_calls)
        attrs["answered_call_history"] = self._answered_calls
        attrs["last_answer_detection"] = self._last_answer_detection
        attrs["answer_detection_enabled"] = True
        attrs["last_updated"] = datetime.now().isoformat()
        return attrs
