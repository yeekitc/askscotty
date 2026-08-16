from django.core.management.base import BaseCommand

from apps.rag.models import CrawlSeed
from apps.rag.seed_urls import SEEDS


class Command(BaseCommand):
    help = "Populate CrawlSeed from the authoritative list in seed_urls.py."

    def handle(self, *args, **options):
        created = 0
        for url, label in SEEDS:
            seed, was_created = CrawlSeed.objects.get_or_create(
                url=url,
                defaults={"label": label},
            )
            if was_created:
                created += 1
            elif seed.label != label:
                seed.label = label
                seed.save(update_fields=["label"])
            self.style.SUCCESS(f"Done. {created} new seeds added ({len(SEEDS)} total).")
        )
