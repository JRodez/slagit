from sharelatex import get_client

import click


@click.group()
def cli():
    pass

@cli.command(help="""
Create a git repository or update an existing one from a sharelatex project
(Note this use the current directory)
""")
@click.argument("project_id")
def init(project_id):
    client = get_client()
    client.download_project(project_id)
