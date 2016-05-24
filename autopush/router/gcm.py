"""GCM Router"""
import gcmclient
import json

from twisted.internet.threads import deferToThread
from twisted.logger import Logger

from autopush.router.interface import RouterException, RouterResponse
from autopush.senderids import SenderIDs


class GCMRouter(object):
    """GCM Router Implementation"""
    log = Logger()
    gcm = None
    dryRun = 0
    collapseKey = "simplepush"

    def __init__(self, ap_settings, router_conf):
        """Create a new GCM router and connect to GCM"""
        self.config = router_conf
        self.min_ttl = router_conf.get("ttl", 60)
        self.dryRun = router_conf.get("dryrun", False)
        self.collapseKey = router_conf.get("collapseKey", "simplepush")
        self.senderIDs = router_conf.get("senderIDs")
        if not self.senderIDs:
            self.senderIDs = SenderIDs(router_conf)
        try:
            senderID = self.senderIDs.choose_ID()
            self.gcm = gcmclient.GCM(senderID.get("auth"))
        except:
            raise IOError("GCM Bridge not initiated in main")
        self.log.debug("Starting GCM router...")

    def check_token(self, token):
        if token not in self.senderIDs.senderIDs():
            return (False, self.senderIDs.choose_ID().get('senderID'))
        return (True, token)

    def amend_msg(self, msg, data=None):
        if data is not None:
            msg["senderid"] = data.get('creds', {}).get('senderID')
        return msg

    def register(self, uaid, router_data, router_token=None, *kwargs):
        """Validate that the GCM Instance Token is in the ``router_data``"""
        if "token" not in router_data:
            raise self._error("connect info missing GCM Instance 'token'",
                              status=401)
        # Assign a senderid
        router_data["creds"] = self.senderIDs.get_ID(router_token)
        return router_data

    def route_notification(self, notification, uaid_data):
        """Start the GCM notification routing, returns a deferred"""
        router_data = uaid_data["router_data"]
        # Kick the entire notification routing off to a thread
        return deferToThread(self._route, notification, router_data)

    def _route(self, notification, router_data):
        """Blocking GCM call to route the notification"""
        data = {"chid": notification.channel_id}
        # Payload data is optional. The endpoint handler validates that the
        # correct encryption headers are included with the data.
        if notification.data:
            mdata = self.config.get('max_data', 4096)
            if len(notification.data) > mdata:
                raise self._error("This message is intended for a " +
                                  "constrained device and is limited " +
                                  "to 3070 bytes. Converted buffer too " +
                                  "long by %d bytes" %
                                  (len(notification.data) - mdata),
                                  413, errno=104)

            data['body'] = notification.data
            data['con'] = notification.headers['content-encoding']
            data['enc'] = notification.headers['encryption']
            data['id'] = notification.version

            if 'crypto-key' in notification.headers:
                data['cryptokey'] = notification.headers['crypto-key']
            elif 'encryption-key' in notification.headers:
                data['enckey'] = notification.headers['encryption-key']

        # registration_ids are the GCM instance tokens (specified during
        # registration.
        router_ttl = notification.ttl or 0
        payload = gcmclient.JSONMessage(
            registration_ids=[router_data.get("token")],
            collapse_key=self.collapseKey,
            time_to_live=max(self.min_ttl, router_ttl),
            dry_run=self.dryRun or ("dryrun" in router_data),
            data=data,
        )
        creds = router_data.get("creds", {"senderID": "missing id"})
        try:
            self.gcm.api_key = creds["auth"]
            result = self.gcm.send(payload)
        except KeyError:
            raise self._error("Server error, missing bridge credentials " +
                              "for %s" % creds.get("senderID"), 500)
        except gcmclient.GCMAuthenticationError, e:
            raise self._error("Authentication Error: %s" % e, 500)
        except Exception, e:
            raise self._error("Unhandled exception in GCM Routing: %s" % e,
                              500)
        return self._process_reply(result)

    def _error(self, err, status, **kwargs):
        """Error handler that raises the RouterException"""
        self.log.debug(err, **kwargs)
        return RouterException(err, status_code=status, response_body=err,
                               **kwargs)

    def _process_reply(self, reply):
        """Process GCM send reply"""
        # acks:
        #  for reg_id, msg_id in reply.success.items():
        # updates
        for old_id, new_id in reply.canonical.items():
            self.log.debug("GCM id changed : {old} => {new}",
                           old=old_id, new=new_id)
            return RouterResponse(status_code=503,
                                  response_body="Please try request again.",
                                  router_data=dict(token=new_id))
        # naks:
        # uninstall:
        for reg_id in reply.not_registered:
            self.log.debug("GCM no longer registered: %s" % reg_id)
            return RouterResponse(
                status_code=410,
                response_body="Endpoint requires client update",
                router_data={},
            )

        #  for reg_id, err_code in reply.failed.items():
        if len(reply.failed.items()) > 0:
            self.log.debug("GCM failures: {failed()}",
                           failed=lambda: json.dumps(reply.failed.items()))
            raise RouterException("GCM failure to deliver", status_code=503,
                                  response_body="Please try request later.")

        # retries:
        if reply.needs_retry():
            raise RouterException("GCM failure to deliver", status_code=503,
                                  response_body="Please try request later.")

        return RouterResponse(status_code=200, response_body="Message Sent")
