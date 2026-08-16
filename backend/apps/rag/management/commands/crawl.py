from django.core.management.base import BaseCommand

from apps.rag.crawler import crawl_seeds
from apps.rag.models import CrawlSeed


class Command(BaseCommand):
    help = "Crawl enabled seeds and save Documents and Chunks."

    def add_arguments(self, parser):
        parser.add_argument("--seed", help="Label of a specific seed to crawl.")
        parser.add_argument(
            "--limit",
            type=int,
            default=500,
            help="Max total pages to crawl across all seeds (default 500).",
        )
        parser.add_argument(
            "--depth",
            type=int,
            default=2,
            help="Max link-hop depth from each seed URL (default 2).",
        )

    def handle(self, *args, **options):
        seeds = CrawlSeed.objects.filter(enabled=True)
        if options["seed"]:
            seeds = seeds.filter(label=options["seed"])

        seeds = list(seeds)
        if not seeds:
            self.stderr.write("No matching seeds found. Run `load_seeds` first.")
            return

        self.stdout.write(
            f"Crawling {len(seeds)} seed(s) "
            f"(limit={options['limit']}, depth={options['depth']})..."
        )
        total = crawl_seeds(
            seeds,
            limit=options["limit"],
            depth=options["depth"],
            stdout=self.stdout,
        )
        self.stdout.write(self.style.SUCCESS(f"Done. {total} pages fetched."))
