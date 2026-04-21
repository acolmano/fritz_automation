"""Services for AVM FRITZ!Box SMS integration."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, TYPE_CHECKING

import voluptuous as vol
from fritzconnection import FritzConnection
from fritzconnection.lib.fritzcall import FritzCall

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, CONF_HOST
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN

if TYPE_CHECKING:
    from . import FritzBoxConfigEntry

_LOGGER = logging.getLogger(__name__)

# SMS Services
SERVICE_GET_SMS = "get_sms"
SERVICE_MARK_SMS_READ = "mark_sms_read"
SERVICE_DELETE_SMS = "delete_sms"
SERVICE_TEST_EVENT = "test_sms_event"
SERVICE_DELETE_ALL_SMS = "delete_all_sms"

# Call Services
SERVICE_MAKE_CALL = "make_call"
SERVICE_HANGUP_CALL = "hangup_call"
SERVICE_DEBUG_METHODS = "debug_methods"
SERVICE_TEST_ANSWER_DETECTION = "test_answer_detection"
SERVICE_TEST_CALL_ANSWERED_EVENT = "test_call_answered_event"
SERVICE_TEST_DYNAMIC_MONITORING = "test_dynamic_monitoring"

SERVICE_GET_SMS_SCHEMA = vol.Schema({
    vol.Optional("limit", default=10): cv.positive_int,
    vol.Optional("unread_only", default=False): cv.boolean,
})

SERVICE_MARK_SMS_READ_SCHEMA = vol.Schema({
    vol.Required("sms_id"): cv.string,
})

SERVICE_DELETE_SMS_SCHEMA = vol.Schema({
    vol.Required("sms_id"): cv.string,
})

SERVICE_MAKE_CALL_SCHEMA = vol.Schema({
    vol.Required("phone_number"): cv.string,
    vol.Optional("caller_phone", default="**610"): cv.string,
    vol.Optional("timeout", default=30): cv.positive_int,
})

SERVICE_HANGUP_CALL_SCHEMA = vol.Schema({
    vol.Optional("call_id"): cv.string,
})


def _create_fritz_connection(host: str, username: str, password: str) -> FritzConnection:
    """Create FritzConnection synchronously (for use in executor)."""
    return FritzConnection(
        address=host,
        user=username,
        password=password
    )


def _make_call_sync(fritz_conn: FritzConnection, phone_number: str, caller_phone: str) -> Any:
    """Make call synchronously (for use in executor)."""
    fritz_call = FritzCall(fritz_conn)
    
    # Documentazione ufficiale: usa dial(number) 
    _LOGGER.info("Using FritzCall.dial() method to dial %s", phone_number)
    
    # Il metodo dial accetta solo il numero, non il telefono chiamante
    result = fritz_call.dial(phone_number)
    
    return {
        "status": "dialed",
        "number": phone_number,
        "result": result,
        "method": "dial"
    }


def _hangup_call_sync(fritz_conn: FritzConnection, call_id: str = None) -> Any:
    """Hangup call synchronously (for use in executor)."""
    fritz_call = FritzCall(fritz_conn)
    
    # Documentazione ufficiale: hangup() non accetta parametri
    _LOGGER.info("Using FritzCall.hangup() method")
    
    # Ignora call_id perché hangup() non lo accetta
    if call_id:
        _LOGGER.warning("call_id parameter ignored - FritzCall.hangup() doesn't support specific call termination")
    
    result = fritz_call.hangup()
    
    return {
        "status": "hangup_requested", 
        "result": result,
        "method": "hangup"
    }


def _get_calls_sync(fritz_conn: FritzConnection) -> list:
    """Get calls synchronously (for use in executor).""" 
    fritz_call = FritzCall(fritz_conn)
    
    # Documentazione ufficiale: get_calls() ritorna lista di oggetti Call
    _LOGGER.info("Using FritzCall.get_calls() method")
    
    calls = fritz_call.get_calls()
    
    # Converti oggetti Call in dizionari per serializzazione
    processed_calls = []
    for call in calls:
        call_data = {
            "id": call.id,  # Convertito automaticamente in int
            "type": call.type,  # Convertito automaticamente in int  
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
            "Path": call.Path,
            "date": call.date.isoformat() if call.date else None,  # datetime convertito
            "duration_seconds": call.duration.total_seconds() if call.duration else None,  # timedelta convertito
        }
        processed_calls.append(call_data)
    
    _LOGGER.info("Retrieved %d calls from FritzCall.get_calls()", len(processed_calls))
    return processed_calls


def _debug_fritz_methods(fritz_conn: FritzConnection) -> dict:
    """Debug FritzConnection methods synchronously (for use in executor)."""
    fritz_call = FritzCall(fritz_conn)
    return {
        "fritz_call_methods": [method for method in dir(fritz_call) if not method.startswith('_')],
        "fritz_conn_methods": [method for method in dir(fritz_conn) if not method.startswith('_')]
    }


async def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for FRITZ!Box SMS integration."""

    async def async_handle_get_sms(call: ServiceCall) -> None:
        """Handle the get_sms service call."""
        _LOGGER.info("Starting get_sms service call")
        
        limit = call.data.get("limit", 10)
        unread_only = call.data.get("unread_only", False)
        
        _LOGGER.debug("Parameters: limit=%s, unread_only=%s", limit, unread_only)
        
        # Trova tutte le config entries per questo dominio
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No FRITZ!Box SMS configuration found")
            return
            
        _LOGGER.debug("Found %d config entries", len(entries))
        
        # Usa la prima configurazione trovata
        config_entry = entries[0]  # Type: FritzBoxConfigEntry
        box = config_entry.runtime_data
        cfg = config_entry.data
        
        _LOGGER.debug("Using config entry: %s", config_entry.title)
        
        try:
            _LOGGER.debug("Attempting to login to FRITZ!Box")
            await box.login(cfg[CONF_USERNAME], cfg[CONF_PASSWORD])
            _LOGGER.debug("Login successful")
            
            sms_list = []
            try:
                _LOGGER.debug("Checking available SMS methods")
                
                # Tentativo di recuperare gli SMS
                if hasattr(box, 'list_sms'):
                    try:
                        all_sms = await box.list_sms(limit=limit)
                    except TypeError:
                        # Metodo non supporta limit
                        all_sms = await box.list_sms()
                elif hasattr(box, 'get_sms_list'):
                    try:
                        all_sms = await box.get_sms_list(limit=limit)
                    except TypeError:
                        # Metodo non supporta limit
                        all_sms = await box.get_sms_list()
                elif hasattr(box, 'get_messages'):
                    try:
                        all_sms = await box.get_messages(limit=limit)
                    except TypeError:
                        # Metodo non supporta limit
                        all_sms = await box.get_messages()
                else:
                    _LOGGER.error("SMS reading method not available")
                    await box.logout()
                    return
                    
                _LOGGER.debug("SMS retrieval result: %s (type: %s)", all_sms, type(all_sms))
                    
                if unread_only and all_sms:
                    # Filtra solo SMS non letti (se l'informazione è disponibile)
                    sms_list = [sms for sms in all_sms if sms.get('unread', True)]
                    _LOGGER.debug("Filtered to unread only: %d SMS", len(sms_list))
                else:
                    sms_list = all_sms or []
                    
            except Exception as err:
                _LOGGER.error("Error retrieving SMS: %s", err, exc_info=True)
                
            await box.logout()
            _LOGGER.debug("Logout successful")
            
            # Emetti un evento con i risultati
            _LOGGER.info("Retrieved %d SMS messages", len(sms_list))
            
            # Emit event per notificare automazioni
            event_data = {
                "sms_count": len(sms_list),
                "sms_list": sms_list,
                "service_call_id": str(call.context.id),
                "timestamp": call.context.origin_event.time_fired.isoformat() if call.context.origin_event else None,
            }
            
            hass.bus.async_fire(
                f"{DOMAIN}_sms_received",
                event_data
            )
            
        except Exception as err:
            _LOGGER.error("Error connecting to FRITZ!Box: %s", err, exc_info=True)
            try:
                await box.logout()
            except:
                pass

    async def async_handle_mark_sms_read(call: ServiceCall) -> None:
        """Handle the mark_sms_read service call."""
        sms_id = call.data["sms_id"]
        
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No FRITZ!Box SMS configuration found")
            return
            
        config_entry = entries[0]  # Type: FritzBoxConfigEntry
        box = config_entry.runtime_data
        cfg = config_entry.data
        
        try:
            await box.login(cfg[CONF_USERNAME], cfg[CONF_PASSWORD])
            
            # Tentativo di marcare come letto
            if hasattr(box, 'mark_sms_read'):
                await box.mark_sms_read(sms_id)
                _LOGGER.info("SMS %s marked as read", sms_id)
            else:
                _LOGGER.warning("Mark SMS as read method not available")
                
            await box.logout()
            
        except Exception as err:
            _LOGGER.error("Error marking SMS as read: %s", err)
            try:
                await box.logout()
            except:
                pass

    async def async_handle_delete_sms(call: ServiceCall) -> None:
        """Handle the delete_sms service call."""
        sms_id = call.data["sms_id"]
        
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No FRITZ!Box SMS configuration found")
            return
            
        config_entry = entries[0]  # Type: FritzBoxConfigEntry
        box = config_entry.runtime_data
        cfg = config_entry.data
        
        try:
            await box.login(cfg[CONF_USERNAME], cfg[CONF_PASSWORD])
            
            # Usa il metodo delete_sms esistente
            if hasattr(box, 'delete_sms'):
                await box.delete_sms(sms_id)
                _LOGGER.info("SMS %s deleted", sms_id)
            else:
                _LOGGER.warning("Delete SMS method not available")
                
            await box.logout()
            
        except Exception as err:
            _LOGGER.error("Error deleting SMS: %s", err)
            try:
                await box.logout()
            except:
                pass
    

    async def async_handle_delete_all_sms(call: ServiceCall) -> None:
        """Handler per il servizio delete_all_sms."""
        _LOGGER.info("Servizio delete_all_sms richiamato")
        
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("Nessuna configurazione FRITZ!Box trovata")
            return
            
        config_entry = entries[0]
        box = config_entry.runtime_data
        cfg = config_entry.data
        
        try:
            _LOGGER.info("Esecuzione login per cancellazione totale")
            await box.login(cfg[CONF_USERNAME], cfg[CONF_PASSWORD])
            await box.delete_all_sms()
            await box.logout()
            _LOGGER.info("Logout completato con successo")
        except Exception as err:
            _LOGGER.error(f"Errore critico durante il servizio di cancellazione: {err}")
            try:
                await box.logout()
            except:
                pass

    async def async_handle_test_event(call: ServiceCall) -> None:
        """Handle the test_sms_event service call to test event emission."""
        _LOGGER.info("Testing SMS event emission")
        
        # Emetti un evento di test
        test_event_data = {
            "test": True,
            "message": "This is a test SMS event",
            "timestamp": call.context.origin_event.time_fired.isoformat() if call.context.origin_event else None,
            "service_call_id": str(call.context.id),
        }
        
        hass.bus.async_fire(f"{DOMAIN}_sms_test", test_event_data)
        _LOGGER.info("Test SMS event emitted successfully")

    async def async_handle_make_call(call: ServiceCall) -> None:
        """Handle the make_call service call using FritzCall."""
        _LOGGER.info("Starting make_call service call")
        
        phone_number = call.data["phone_number"]
        caller_phone = call.data.get("caller_phone", "**610")
        timeout = call.data.get("timeout", 30)
        
        _LOGGER.debug("Parameters: phone_number=%s, caller_phone=%s, timeout=%s", 
                     phone_number, caller_phone, timeout)
        
        # Trova la configurazione
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No FRITZ!Box SMS configuration found")
            return
            
        config_entry = entries[0]
        cfg = config_entry.data
        
        try:
            # Crea connessione FritzConnection in un executor (non blocking)
            _LOGGER.debug("Creating FritzConnection in executor")
            fritz_conn = await hass.async_add_executor_job(
                _create_fritz_connection,
                cfg.get(CONF_HOST, "192.168.178.1"),
                cfg[CONF_USERNAME],
                cfg[CONF_PASSWORD]
            )
            
            _LOGGER.debug("Attempting to make call in executor")
            
            # Effettua la chiamata in un executor
            call_result = await hass.async_add_executor_job(
                _make_call_sync,
                fritz_conn,
                phone_number,
                caller_phone
            )
            
            _LOGGER.info("Call initiated successfully: %s", call_result)
            
            # Emetti evento per notificare automazioni
            event_data = {
                "phone_number": phone_number,
                "caller_phone": caller_phone,
                "call_result": call_result,
                "service_call_id": str(call.context.id),
                "timestamp": call.context.origin_event.time_fired.isoformat() if call.context.origin_event else None,
            }
            
            hass.bus.async_fire(f"{DOMAIN}_call_made", event_data)
            
        except Exception as err:
            _LOGGER.error("Error making call: %s", err, exc_info=True)
            
            # Emetti evento di errore
            error_event_data = {
                "error": str(err),
                "phone_number": phone_number,
                "service_call_id": str(call.context.id),
                "timestamp": call.context.origin_event.time_fired.isoformat() if call.context.origin_event else None,
            }
            
            hass.bus.async_fire(f"{DOMAIN}_call_error", error_event_data)

    async def async_handle_hangup_call(call: ServiceCall) -> None:
        """Handle the hangup_call service call using FritzCall."""
        _LOGGER.info("Starting hangup_call service call")
        
        call_id = call.data.get("call_id")
        
        _LOGGER.debug("Parameters: call_id=%s", call_id)
        
        # Trova la configurazione
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No FRITZ!Box SMS configuration found")
            return
            
        config_entry = entries[0]
        cfg = config_entry.data
        
        try:
            # Crea connessione FritzConnection in un executor
            _LOGGER.debug("Creating FritzConnection in executor")
            fritz_conn = await hass.async_add_executor_job(
                _create_fritz_connection,
                cfg.get(CONF_HOST, "192.168.178.1"),
                cfg[CONF_USERNAME],
                cfg[CONF_PASSWORD]
            )
            
            _LOGGER.debug("Attempting to hangup call in executor")
            
            # Termina la chiamata in un executor
            hangup_result = await hass.async_add_executor_job(
                _hangup_call_sync,
                fritz_conn,
                call_id
            )
            
            _LOGGER.info("Call hangup successful: %s", hangup_result)
            
            # Emetti evento per notificare automazioni
            event_data = {
                "call_id": call_id,
                "hangup_result": hangup_result,
                "service_call_id": str(call.context.id),
                "timestamp": call.context.origin_event.time_fired.isoformat() if call.context.origin_event else None,
            }
            
            hass.bus.async_fire(f"{DOMAIN}_call_hangup", event_data)
            
        except Exception as err:
            _LOGGER.error("Error hanging up call: %s", err, exc_info=True)
            
            # Emetti evento di errore
            error_event_data = {
                "error": str(err),
                "call_id": call_id,
                "service_call_id": str(call.context.id),
                "timestamp": call.context.origin_event.time_fired.isoformat() if call.context.origin_event else None,
            }
            
            hass.bus.async_fire(f"{DOMAIN}_hangup_error", error_event_data)

    async def async_handle_debug_methods(call: ServiceCall) -> None:
        """Handle the debug_methods service call to list available methods."""
        _LOGGER.info("Starting debug_methods service call")
        
        # Trova la configurazione
        entries = hass.config_entries.async_entries(DOMAIN)
        if not entries:
            _LOGGER.error("No FRITZ!Box SMS configuration found")
            return
            
        config_entry = entries[0]
        cfg = config_entry.data
        
        try:
            # Debug per pyfritzsms (oggetto box)
            box = config_entry.runtime_data
            await box.login(cfg[CONF_USERNAME], cfg[CONF_PASSWORD])
            
            _LOGGER.info("=== PYFRITZSMS BOX METHODS ===")
            box_methods = [method for method in dir(box) if not method.startswith('_')]
            for method in sorted(box_methods):
                _LOGGER.info("pyfritzsms.%s", method)
            
            await box.logout()
            
            # Debug per fritzconnection in executor
            _LOGGER.info("=== FRITZCONNECTION METHODS ===")
            fritz_conn = await hass.async_add_executor_job(
                _create_fritz_connection,
                cfg.get(CONF_HOST, "192.168.178.1"),
                cfg[CONF_USERNAME],
                cfg[CONF_PASSWORD]
            )
            
            fritz_methods = await hass.async_add_executor_job(
                _debug_fritz_methods,
                fritz_conn
            )
            
            for method in sorted(fritz_methods["fritz_call_methods"]):
                _LOGGER.info("fritzconnection.FritzCall.%s", method)
            
            # Emetti evento di debug
            debug_event_data = {
                "pyfritzsms_methods": box_methods,
                "fritzconnection_call_methods": fritz_methods["fritz_call_methods"],
                "fritzconnection_conn_methods": fritz_methods["fritz_conn_methods"],
                "service_call_id": str(call.context.id),
                "timestamp": call.context.origin_event.time_fired.isoformat() if call.context.origin_event else None,
            }
            
            hass.bus.async_fire(f"{DOMAIN}_debug_methods", debug_event_data)
            
        except Exception as err:
            _LOGGER.error("Error in debug methods: %s", err, exc_info=True)

    async def async_handle_test_answer_detection(call: ServiceCall) -> None:
        """Test the call answer detection system."""
        _LOGGER.info("Testing call answer detection system")
        
        try:
            # Simula transizioni di chiamata per test
            test_scenarios = [
                {
                    "scenario": "Outbound call answered",
                    "transition": "11→3",
                    "previous": {"id": 123, "type": 11, "duration_seconds": 0},
                    "current": {"id": 123, "type": 3, "duration_seconds": 45}
                },
                {
                    "scenario": "Inbound call answered", 
                    "transition": "9→1",
                    "previous": {"id": 124, "type": 9, "duration_seconds": 0},
                    "current": {"id": 124, "type": 1, "duration_seconds": 120}
                },
                {
                    "scenario": "Inbound call missed",
                    "transition": "9→2", 
                    "previous": {"id": 125, "type": 9, "duration_seconds": 0},
                    "current": {"id": 125, "type": 2, "duration_seconds": 0}
                },
                {
                    "scenario": "Inbound call rejected",
                    "transition": "9→10",
                    "previous": {"id": 126, "type": 9, "duration_seconds": 0},
                    "current": {"id": 126, "type": 10, "duration_seconds": 0}
                }
            ]
            
            test_results = []
            
            for scenario in test_scenarios:
                # Simula la logica di rilevamento risposta
                prev_type = scenario["previous"]["type"]
                curr_type = scenario["current"]["type"]
                duration = scenario["current"]["duration_seconds"]
                
                answer_transitions = {
                    (11, 3): "outbound_answered",
                    (9, 1): "inbound_answered", 
                    (9, 2): "inbound_missed",
                    (9, 10): "inbound_rejected",
                }
                
                transition_key = (prev_type, curr_type)
                answer_type = answer_transitions.get(transition_key, "unknown")
                
                result = {
                    "scenario": scenario["scenario"],
                    "transition": scenario["transition"],
                    "answer_type": answer_type,
                    "duration": duration,
                    "answered": answer_type in ["outbound_answered", "inbound_answered"] and duration > 0
                }
                
                test_results.append(result)
                _LOGGER.info("Test scenario: %s → %s (Duration: %ds)", 
                           scenario["scenario"], answer_type, duration)
            
            # Emetti evento con risultati test
            hass.bus.async_fire(f"{DOMAIN}_answer_detection_test", {
                "test_results": test_results,
                "timestamp": datetime.now().isoformat(),
                "service_call_id": str(call.context.id)
            })
            
            _LOGGER.info("Answer detection test completed: %d scenarios tested", len(test_results))
            
        except Exception as err:
            _LOGGER.error("Error in test_answer_detection: %s", err, exc_info=True)
            hass.bus.async_fire(f"{DOMAIN}_answer_detection_test_error", {"error": str(err)})

    async def async_handle_test_call_answered_event(call: ServiceCall) -> None:
        """Test the call_answered event emission."""
        _LOGGER.info("Testing call_answered event emission")
        
        # Parametri dal servizio o valori di default
        call_id = call.data.get("call_id", 99999)
        answer_type = call.data.get("answer_type", "inbound_answered")
        transition = call.data.get("transition", "9→1")
        caller = call.data.get("caller", "Test User")
        caller_number = call.data.get("caller_number", "+39000000000")
        
        # Simula informazioni chiamata complete
        test_call_info = {
            "id": call_id,
            "type": 1,  # Chiamata risposta
            "Called": "",
            "Caller": caller,
            "CallerNumber": caller_number,
            "CalledNumber": "",
            "Name": caller,
            "Device": "FRITZ!Box Test",
            "Port": "",
            "Date": datetime.now().strftime("%d.%m.%y %H:%M"),
            "Duration": "0:01:30",
            "Count": "",
            "Path": "",
            "date": datetime.now().isoformat(),
            "duration_seconds": 90.0,
        }
        
        # Emetti evento di test
        test_event_data = {
            "call_id": call_id,
            "answer_type": answer_type,
            "transition": transition,
            "call_info": test_call_info,
            "timestamp": datetime.now().isoformat(),
            "test": True,  # Indica che è un evento di test
            "service_call_id": str(call.context.id),
        }
        
        hass.bus.async_fire(f"{DOMAIN}_call_answered", test_event_data)
        _LOGGER.info("Test call_answered event emitted: %s (call_id: %s)", answer_type, call_id)

    async def async_handle_test_dynamic_monitoring(call: ServiceCall) -> None:
        """Test the dynamic monitoring system by simulating call states."""
        _LOGGER.info("Testing dynamic call monitoring system")
        
        # Trova il sensore call_status
        entities = hass.states.async_all()
        call_status_entity = None
        
        for entity in entities:
            if entity.entity_id == "sensor.fritzsms_call_status":
                call_status_entity = entity
                break
        
        if not call_status_entity:
            _LOGGER.error("Call status sensor not found for dynamic monitoring test")
            return
        
        # Ottieni informazioni correnti
        attributes = call_status_entity.attributes
        current_mode = attributes.get("monitoring_mode", "unknown")
        current_interval = attributes.get("update_interval_seconds", "unknown")
        active_calls = attributes.get("active_calls", 0)
        
        # Simula risultati del test
        test_info = {
            "current_monitoring_mode": current_mode,
            "current_update_interval": current_interval,
            "active_calls_detected": active_calls,
            "expected_behavior": {
                "no_calls": "30 seconds interval (normal mode)",
                "active_calls": "5 seconds interval (active mode)", 
                "after_calls": "5 seconds for 60 seconds, then back to 30"
            },
            "test_timestamp": datetime.now().isoformat(),
            "instructions": [
                "1. Make a call to FRITZ!Box to activate rapid monitoring",
                "2. Watch monitoring_mode change to 'active'", 
                "3. Watch update_interval_seconds change to 5",
                "4. After call ends, rapid mode continues for 60 seconds",
                "5. Then returns to normal mode (30 seconds)"
            ]
        }
        
        # Emetti evento di test
        hass.bus.async_fire(f"{DOMAIN}_dynamic_monitoring_test", test_info)
        
        _LOGGER.info("Dynamic monitoring test info emitted")
        _LOGGER.info("Current mode: %s, interval: %s seconds", current_mode, current_interval)

    # Registra i servizi SMS
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_SMS,
        async_handle_get_sms,
        schema=SERVICE_GET_SMS_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_SMS_READ,
        async_handle_mark_sms_read,
        schema=SERVICE_MARK_SMS_READ_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_SMS,
        async_handle_delete_sms,
        schema=SERVICE_DELETE_SMS_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_DELETE_ALL_SMS,
        async_handle_delete_all_sms,
    )
    
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_EVENT,
        async_handle_test_event,
    )
    
    # Registra i servizi di chiamata
    hass.services.async_register(
        DOMAIN,
        SERVICE_MAKE_CALL,
        async_handle_make_call,
        schema=SERVICE_MAKE_CALL_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_HANGUP_CALL,
        async_handle_hangup_call,
        schema=SERVICE_HANGUP_CALL_SCHEMA,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_DEBUG_METHODS,
        async_handle_debug_methods,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_ANSWER_DETECTION,
        async_handle_test_answer_detection,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_CALL_ANSWERED_EVENT,
        async_handle_test_call_answered_event,
    )
    
    hass.services.async_register(
        DOMAIN,
        SERVICE_TEST_DYNAMIC_MONITORING,
        async_handle_test_dynamic_monitoring,
    )


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload services for FRITZ!Box SMS integration."""
    # Rimuovi servizi SMS
    hass.services.async_remove(DOMAIN, SERVICE_GET_SMS)
    hass.services.async_remove(DOMAIN, SERVICE_MARK_SMS_READ)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_SMS)
    hass.services.async_remove(DOMAIN, SERVICE_TEST_EVENT)
    
    # Rimuovi servizi di chiamata
    hass.services.async_remove(DOMAIN, SERVICE_MAKE_CALL)
    hass.services.async_remove(DOMAIN, SERVICE_HANGUP_CALL)
    hass.services.async_remove(DOMAIN, SERVICE_DEBUG_METHODS)
    hass.services.async_remove(DOMAIN, SERVICE_TEST_ANSWER_DETECTION)
    hass.services.async_remove(DOMAIN, SERVICE_TEST_CALL_ANSWERED_EVENT)
    hass.services.async_remove(DOMAIN, SERVICE_TEST_DYNAMIC_MONITORING)
