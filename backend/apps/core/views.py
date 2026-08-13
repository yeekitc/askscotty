from datetime import datetime, timezone

from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import AskSerializer


class HealthView(APIView):
    authentication_classes: list = []
    permission_classes: list = []

    def get(self, request: Request) -> Response:
        return Response(
            {
                "status": "ok",
                "service": "askscotty-backend",
                "time": datetime.now(timezone.utc).isoformat(),
            }
        )


class AskView(APIView):
    """Stub planner endpoint — replace with RAG + live tools per PRD."""

    authentication_classes: list = []
    permission_classes: list = []

    def post(self, request: Request) -> Response:
        serializer = AskSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        query = serializer.validated_data["query"]

        now = datetime.now(timezone.utc).isoformat()
        return Response(
            {
                "answer": (
                    f'Stub response for: "{query}". '
                    "Wire this to the planner (RAG → live tools → web verify) described in PRD.md."
                ),
                "citations": [
                    {
                        "title": "Product requirements",
                        "url": "",
                        "source": "PRD",
                        "indexed_at": now,
                        "verified_at": now,
                    }
                ],
                "modes_used": ["stub"],
                "note": "Demo stub — not live campus data.",
            },
            status=status.HTTP_200_OK,
        )
