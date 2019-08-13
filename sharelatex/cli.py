import json
import logging
from pathlib import Path
import time

from sharelatex import get_client, walk_files

import click
from git import Repo
from zipfile import ZipFile

logger = logging.getLogger(__name__)
SHARELATEX_FILE = ".sharelatex"
SYNC_BRANCH = "__remote__sharelatex__"


logging.basicConfig(level=logging.DEBUG)


@click.group()
def cli():
    pass


def get_clean_repo():
    repo = Repo.init()
    # Fail if the repo is clean
    if repo.is_dirty(index=True, working_tree=True, untracked_files=True):
        print(repo.git.status())
        raise Exception("The repo isn't clean")
    return repo


def update_ref(repo):
    git = repo.git
    git.add(".")
    git.commit("-m 'resync'")
    sync_branch = repo.create_head(SYNC_BRANCH, force=True)
    sync_branch.commit = "HEAD"


@cli.command(
    help="""
Pull the files from sharelatex.
(Note this uses the current directory)
"""
)
@click.argument("project_id", default="")
def pull(project_id):
    client = get_client()
    repo = get_clean_repo()

    if project_id == "":
        with open(SHARELATEX_FILE, "r") as f:
            project_data = json.load(f)
        project_id = project_data["_id"]
    else:
        project_data = client.get_project_data(project_id)
        with open(SHARELATEX_FILE, "w") as f:
            f.write(json.dumps(project_data, indent=4))
    client.download_project(project_id)

    # TODO(msimonin): add a decent default .gitignore ?
    update_ref(repo)


@cli.command(help="Push the commited changes back to sharelatex")
def push():
    client = get_client()
    repo = Repo()
    # Fail if the repo is clean
    if repo.is_dirty(index=True, working_tree=True, untracked_files=True):
        print(repo.git.status())
        print("The repository isn't clean")
        return
    tree = repo.tree()
    # reload .sharelatex
    # TODO(msimonin): handle errors
    #   - non existent
    #   - non readable...
    # TODO(msimonin): take the git tree instead of reloading the .sharelatex
    sharelatex_file = list(tree.traverse(lambda i, d: i.path == SHARELATEX_FILE))[0]
    with open(sharelatex_file.abspath, "r") as f:
        project_data = json.load(f)

    project_id = project_data["_id"]

    # First iteration, we push we have in the project data
    # limitations: modification on the local tree (folder, file creation) will
    # not be propagated
    iter = walk_files(project_data)
    for i in iter:
        # the / at the beginnning of i["folder_path"] makes the join to forget
        # about the working dir
        # path = os.path.join(repo.working_dir, i["folder_path"], i["name"])
        path = f"{repo.working_dir}{i['folder_path']}/{i['name']}"
        client.upload_file(project_id, i["folder_id"], path)


@cli.command(help="Upload the current directory as a new sharelatex project")
@click.argument("name")
def upload(name):
    # check if we're on a git repo
    client = get_client()
    repo = get_clean_repo()
    iter_file = repo.tree().traverse()
    archive_name = "%s.zip" % name
    archive_path = Path(archive_name)
    with ZipFile(str(archive_path), "w") as z:
        for f in iter_file:
            logging.debug(f"Adding {f.path} to the archive")
            z.write(f.path)

    response = client.upload(archive_name)
    print("Successfully uploaded %s [%s]" % (name, response["project_id"]))

    # TODO(msimonin): the following is starting to feel like the init
    # there's an opportunity to factorize both
    project_data = client.get_project_data(response["project_id"])
    with open(SHARELATEX_FILE, "w") as f:
        f.write(json.dumps(project_data, indent=4))

    archive_path.unlink()

    update_ref(repo)
