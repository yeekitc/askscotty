from django.core.management.base import BaseCommand

from apps.rag.embedder import embed_pending


class Command(BaseCommand):
    help = "Embed pending Chunks and populate Chunk.embedding."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Re-embed all chunks, not just those missing an embedding.",
        )

    def handle(self, *args, **options):
        total = embed_pending(force=options["force"], stdout=self.stdout)
        self.stdout.write(self.style.SUCCESS(f"Done. {total} chunks embedded."))
