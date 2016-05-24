.. _websocket_module:

:mod:`autopush.websocket`
-------------------------

.. automodule:: autopush.websocket

.. _websocket_protocol:

Websocket Protocol
++++++++++++++++++

.. autoclass:: PushServerProtocol
    :members:
    :special-members: __init__
    :private-members:
    :member-order: bysource

HTTP Handlers
+++++++++++++

.. autoclass:: RouterHandler
    :members:
    :member-order: bysource

.. autoclass:: NotificationHandler
    :members:
    :member-order: bysource


Utility Functions
+++++++++++++++++

.. autofunction:: ms_time

.. autofunction:: periodic_reporter

.. autofunction:: log_exception
