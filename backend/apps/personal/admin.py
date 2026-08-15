# UserConnection is deliberately NOT registered here.
#
# The Django admin renders every field of a model it manages, so registering
# this one would put credential ciphertext on a web page and into admin history
# — the accident PRD §9 is written to prevent.
#
# To inspect connections while debugging, use the shell instead:
#   docker compose exec backend python manage.py shell
#   >>> from apps.personal.models import UserConnection
#   >>> UserConnection.objects.values("session_id", "provider", "last_sync_at")
