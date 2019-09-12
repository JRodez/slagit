from contextlib import contextmanager
import os
from sharelatex import SyncClient
from subprocess import check_call
import tempfile
import unittest



BASE_URL = os.environ.get("CI_BASE_URL")
USERNAME = os.environ.get("CI_USERNAME")
PASSWORD = os.environ.get("CI_PASSWORD")


def log(f):
    def wrapped(*args, **kwargs):
        print("-"*60)
        print("{:^60}".format(f.__name__.upper()))
        print("-"*60)
        return f(*args, **kwargs)
    return wrapped

@contextmanager
def project(project_name):
    client = SyncClient(base_url=BASE_URL, username=USERNAME, password=PASSWORD)
    with tempfile.TemporaryDirectory() as temp_path:
        os.chdir(temp_path)
        r = client.new(project_name)
        project_id = r["project_id"]
        path = os.path.join(temp_path, project_id)
        # TODO(msimonin) yield the repo object also
        yield (client, path, project_id)
        client.delete(project_id, forever=True)

class TestCli(unittest.TestCase):

    def test_clone(self):
        with project("clone") as (_, _, project_id):
            url = f"{BASE_URL}/project/{project_id}"
            check_call(
                f"git slatex clone {url} --username={USERNAME} --password={PASSWORD} --save-password",
                shell=True,
            )

    def test_clone_and_push(self):
        with project("clone_and_pull") as (_, path, project_id):
            url = f"{BASE_URL}/project/{project_id}"
            check_call(
                f"git slatex clone {url} --username={USERNAME} --password={PASSWORD} --save-password",
                shell=True,
            )
            os.chdir(path)
            check_call("git slatex pull", shell=True)