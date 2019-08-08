import json
import logging
import os

from sharelatex import get_client, walk_project_data

import click
from git import Repo

logger = logging.getLogger(__name__)
SHARELATEX_FILE = ".sharelatex"


@click.group()
def cli():
    pass


@cli.command(
    help="""
Create a git repository or update an existing one from a sharelatex project
(Note this use the current directory)
"""
)
@click.argument("project_id")
def init(project_id):
    client = get_client()
    project_data = client.get_project_data(project_id)
    with open(SHARELATEX_FILE, "w") as f:
        f.write(json.dumps(project_data, indent=4))
    client.download_project(project_id)

    # quick way to get the repo resync the repo
    # issue: when we already are in a git repo (by mistake)
    # this will commit everything on top
    repo = Repo.init()
    git = repo.git
    git.add(".")
    git.commit("-m 'resync'")


@cli.command(help="Push the commited changes back to sharelatex")
def push():
    client = get_client()
    repo = Repo()
    # Check if the repo is clean
    if repo.is_dirty(index=True, working_tree=True, untracked_files=True):
        print(repo.git.status())
        print("The repository isn't clean")
        return
    tree = repo.tree()
    # reload .sharelatex
    # TODO(msimonin): handle errors
    #   - non existent
    #   - non readable...
    sharelatex_file = list(tree.traverse(lambda i, d: i.path == SHARELATEX_FILE))[0]
    with open(sharelatex_file.abspath, "r") as f:
        project_data = json.load(f)

    project_id = project_data["_id"]

    # First iteration, we push we have in the project data
    # limitations: modification on the local tree (folder, file creation) will
    # not be propagated
    iter = walk_project_data(project_data)
    for i in iter:
        # the / at the beginnning of i["folder_path"] makes the join to forget
        # about the working dir
        # path = os.path.join(repo.working_dir, i["folder_path"], i["name"])
        path = f"{repo.working_dir}{i['folder_path']}/{i['name']}"
        client.upload(project_id, i["folder_id"], path)
