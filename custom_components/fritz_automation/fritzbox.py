import asyncio
import logging
from aiohttp import BasicAuth

"""FRITZ!Box SMS client implementation."""

import hashlib
import pyotp
from aiohttp import ClientSession
from xml.etree import ElementTree

DATA_URL = "http://{}/data.lua"
LOGIN_URL = "http://{}/login_sid.lua"
TWOFACTOR_URL = "http://{}/twofactor.lua"


class FritzBox:

    async def hangup_call(self, username: str, password: str):
        """Hang up the current call using TR-064 X_AVM-DE_DialHangup action."""
        # TR-064 endpoint and service details
        control_url = f"http://{self._host}:49000/upnp/control/x_voip"
        service_type = "urn:dslforum-org:service:X_VoIP:1"
        soap_action = 'urn:dslforum-org:service:X_VoIP:1#X_AVM-DE_DialHangup'
        soap_body = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
            's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
            '<s:Body>'
            '<u:X_AVM-DE_DialHangup xmlns:u="urn:dslforum-org:service:X_VoIP:1" />'
            '</s:Body>'
            '</s:Envelope>'
        )
        headers = {
            'Content-Type': 'text/xml; charset="utf-8"',
            'SOAPACTION': soap_action,
        }
        # Use basic auth for TR-064
        auth = BasicAuth(username, password)
        try:
            async with self._session.post(control_url, data=soap_body, headers=headers, auth=auth, timeout=5) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logging.error(f"FritzBox hangup failed: {resp.status} {text}")
                    raise RuntimeError(f"FritzBox hangup failed: {resp.status}")
                logging.debug("FritzBox hangup command sent successfully.")
                return True
        except Exception as ex:
            logging.error(f"FritzBox hangup exception: {ex}")
            return False
    """FRITZ!Box SMS client."""
    
    def __init__(self, host: str, session: ClientSession):
        """Initialize FRITZ!Box client.
        
        Args:
            host: FRITZ!Box hostname or IP address
            session: aiohttp ClientSession
        """
        self._host = host
        self._session = session
        self._sid = ""
        self._otp = None

    def set_otp(self, otp_secret: str):
        """Set TOTP secret for two-factor authentication.
        
        Args:
            otp_secret: TOTP secret string
        """
        self._otp = pyotp.TOTP(otp_secret)

    def get_otp(self):
        """Get current TOTP code.
        
        Returns:
            Current TOTP code
            
        Raises:
            RuntimeError: If TOTP secret is not set
        """
        if not self._otp:
            raise RuntimeError("TOTP secret is not set")
        return self._otp.now()

    def _check_status(self, response):
        """Check HTTP response status.
        
        Args:
            response: aiohttp response object
            
        Raises:
            RuntimeError: If status is not 200
        """
        if response.status != 200:
            raise RuntimeError(f"Unexpected response from FritzBox: {response.status}")

    async def login(self, username: str, password: str):
        """Login to FRITZ!Box.
        
        Args:
            username: Username
            password: Password
            
        Returns:
            Session ID
        """
        # Get challenge
        async with self._session.get(LOGIN_URL.format(self._host)) as response:
            self._check_status(response)
            text = await response.text()
            tree = ElementTree.fromstring(text)
            challenge = tree.findtext("Challenge")
            
        # Calculate response hash
        md5hash = (
            hashlib.md5((challenge + "-" + password).encode("utf-16le"))
            .hexdigest()
            .lower()
        )
        response_hash = challenge + "-" + md5hash
        
        # Perform login
        async with self._session.post(
            LOGIN_URL.format(self._host),
            data={
                "username": username,
                "response": response_hash,
            },
        ) as response:
            self._check_status(response)
            text = await response.text()
            tree = ElementTree.fromstring(text)
            self._sid = tree.findtext("SID").strip("0")
            
        return self._sid

    async def logout(self):
        """Logout from FRITZ!Box.
        
        Returns:
            Session ID (should be empty after logout)
        """
        async with self._session.get(
            LOGIN_URL.format(self._host),
            params={
                "sid": self._sid,
                "logout": "1",
            },
        ) as response:
            self._check_status(response)
            text = await response.text()
            tree = ElementTree.fromstring(text)
            self._sid = tree.findtext("SID").strip("0")
            
        return self._sid

    async def is_otp_configured(self):
        """Check if TOTP is configured.
        
        Returns:
            True if TOTP is configured, False otherwise
        """
        async with self._session.post(
            TWOFACTOR_URL.format(self._host),
            data={
                "sid": self._sid,
                "tfa_googleauth_info": "",
                "no_sidrenew": "",
            },
        ) as response:
            self._check_status(response)
            data = await response.json()
            
        return data["googleauth"]["isConfigured"]

    async def list_sms(self):
        """List SMS messages.
        
        Returns:
            List of SMS messages
        """
        async with self._session.post(
            DATA_URL.format(self._host),
            data={
                "sid": self._sid,
                "page": "smsList",
            },
        ) as response:
            self._check_status(response)
            data = await response.json()
            
        messages = data["data"]["smsListData"]["messages"]
        return messages

    async def delete_sms(self, message_id: int):
        """Delete an SMS message.
        
        Args:
            message_id: ID of the message to delete
            
        Raises:
            RuntimeError: If SMS could not be deleted
        """
        async with self._session.post(
            DATA_URL.format(self._host),
            data={
                "sid": self._sid,
                "page": "smsList",
                "messageId": message_id,
                "delete": "",
            },
        ) as response:
            self._check_status(response)
            data = await response.json()
            
        if "sid" in data:
            self._sid = data["sid"]
            
        if data["data"].get("delete") != "ok":
            raise RuntimeError("SMS could not be deleted")

    
    async def send_sms(self, number: str, message: str):
        """Send an SMS message.
        
        Args:
            number: Phone number to send to
            message: Message text
        
        Returns:
            Message UID or True if successful
            
        Raises:
            RuntimeError: If SMS could not be sent
        """
        # Initial request to send SMS
        async with self._session.post(
            DATA_URL.format(self._host),
            data={
                "sid": self._sid,
                "page": "smsSendMsg",
                "recipient": number,
                "newMessage": message,
                "apply": "true",
            },
        ) as response:
            self._check_status(response)
            data = await response.json()
            
        if "sid" in data:
            self._sid = data["sid"]
            
        if "new_uid" not in data["data"]:
            return True

        # Second factor required via TOTP
        new_uid = data["data"]["new_uid"]
        async with self._session.post(
            DATA_URL.format(self._host),
            data={
                "sid": self._sid,
                "page": "smsSendMsg",
                "recipient": number,
                "newMessage": message,
                "new_uid": new_uid,
                "second_apply": "",
            },
        ) as response:
            self._check_status(response)
            data = await response.json()
            
        if "sid" in data:
            self._sid = data["sid"]
            
        if data["data"]["second_apply"] != "twofactor":
            raise RuntimeError("TOTP is not required")

        # Check if TOTP is configured and available
        async with self._session.post(
            TWOFACTOR_URL.format(self._host),
            data={
                "sid": self._sid,
                "tfa_googleauth_info": "",
                "no_sidrenew": "",
            },
        ) as response:
            self._check_status(response)
            data = await response.json()
            
        if not data["googleauth"]["isConfigured"]:
            raise RuntimeError("TOTP is not configured")
        if not data["googleauth"]["isAvailable"]:
            raise RuntimeError("TOTP is not available")

        # Send TOTP
        async with self._session.post(
            TWOFACTOR_URL.format(self._host),
            data={
                "sid": self._sid,
                "tfa_googleauth": self.get_otp(),
                "no_sidrenew": "",
            },
        ) as response:
            self._check_status(response)
            data = await response.json()
            
        if data["err"] != 0:
            raise RuntimeError("TOTP is not valid")

        # Check if TOTP is active and done
        async with self._session.post(
            TWOFACTOR_URL.format(self._host),
            data={
                "sid": self._sid,
                "tfa_active": "",
                "no_sidrenew": "",
            },
        ) as response:
            self._check_status(response)
            data = await response.json()
            
        if not data["active"]:
            raise RuntimeError("TOTP is not active")
        if not data["done"]:
            raise RuntimeError("TOTP is not done")

        # Finally send SMS again
        async with self._session.post(
            DATA_URL.format(self._host),
            data={
                "sid": self._sid,
                "page": "smsSendMsg",
                "recipient": number,
                "newMessage": message,
                "new_uid": new_uid,
                "second_apply": "",
                "confirmed": "",
                "twofactor": "",
            },
        ) as response:
            self._check_status(response)
            data = await response.json()
            
        if "sid" in data:
            self._sid = data["sid"]
            
        if data["data"]["second_apply"] != "ok":
            raise RuntimeError("TOTP is not ok")
            
        return new_uid
