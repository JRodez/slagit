import click

@click.group()
def cli():
    pass

@cli.command(help="Hello from sharelatex")
def hello():
    print("Hello")
