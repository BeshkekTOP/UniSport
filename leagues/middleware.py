from .models import AuditLog


class AuditLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = request.user if getattr(request, "user", None) and request.user.is_authenticated else None
        xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
        ip = (xff.split(",")[0].strip() if xff else request.META.get("REMOTE_ADDR", ""))[:64]
        try:
            AuditLog.objects.create(
                user=user,
                method=request.method[:10],
                path=request.path[:300],
                status_code=int(getattr(response, "status_code", 200)),
                ip=ip,
            )
        except Exception:
            # Audit logging should never break app flow.
            pass
        return response
