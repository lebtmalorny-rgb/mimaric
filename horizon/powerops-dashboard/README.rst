PowerOps Horizon dashboard
==========================

``powerops-dashboard`` is a dedicated Horizon 2025.1 interface for the fixed
PowerOps workflows exposed by Mistral.  It never connects directly to Nova,
Masakari, Ironic or a BMC.

Local mock preview
------------------

The preview uses secret-free local fixtures and disables every mutation.  It
does not require OpenStack credentials and must be bound only to loopback::

  python manage.py runserver \
    --settings=poweropsdashboard.test.preview_settings \
    127.0.0.1:8000

Open ``http://127.0.0.1:8000/powerops/``.  Inventory, execution and return
pages are read from defensive fixture copies.  Planned, return-start and
return-resume POST requests fail with HTTP 409 because mock mutation methods
always raise ``MockMutationDisabled``.

The mock preview is structural UI evidence only.  It does not prove deployed
Horizon, Mistral, Nova, Masakari, Ironic, etcd or hardware compatibility.
