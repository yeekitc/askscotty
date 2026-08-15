# UserConnection is deliberately NOT registered here.
#
# The Django admin renders every field of a model it manages, so registering
# this one would put credential ciphertext on a web page and into admin history
# — the exact class of accident PRD §9 is written to prevent. There is no
# read-only-fields configuration that makes that a good trade for a hackathon
# demo, so the model simply stays out of the admin.
#
# To inspect connections while debugging, use the shell instead:
#   docker compose exec backend python manage.py shell
#   >>> from apps.personal.models import UserConnection
#   >>> UserConnection.objects.values("session_id", "provider", "last_sync_at")
