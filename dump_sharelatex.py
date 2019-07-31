import re
import getpass
import os
import requests
import zipfile


BASE_URL = "https://sharelatex.irisa.fr"
LOGIN_URL = "{}/login".format(BASE_URL)
print("email: ")
EMAIL = input()
PASSWORD = getpass.getpass()



def init_client():
    client = requests.session()

    # Retrieve the CSRF token first
    r = client.get(LOGIN_URL, verify=True)
    csrftoken = re.search('(?<=csrfToken = ").{36}', r.text).group(0)
    # login
    login_data = {"email": EMAIL,
                "password": PASSWORD,
                "_csrf":csrftoken}
    return client, login_data


def browse_project(client,login_data, project_id, path='.'):
    r = client.post(LOGIN_URL, data=login_data, verify=True)
    project_url= "{base}/project/{pid}".format(base=BASE_URL,
                                                pid=project_id)
    r = client.get(project_url)

def download_project(client,login_data,project_id, path='.'):
    zip_url = "{base}/project/{pid}/download/zip".format(base=BASE_URL,
                                                         pid=project_id)

    r = client.post(LOGIN_URL, data=login_data, verify=True)
    r = client.get(zip_url, stream=True)

    print("Downloading")
    target_path = os.path.join(path, "{}.zip".format(project_id))
    with open(target_path, 'wb') as f:
        for chunk in r.iter_content(chunk_size=1024):
            if chunk:
                f.write(chunk)

    print("Unzipping ....")
    zip_file = zipfile.ZipFile(target_path)
    zip_file.extractall(path)
    zip_file.close()

# pip install socketIO-client==0.5.7.4
from socketIO_client import SocketIO, BaseNamespace
def get_project_data(client,login_data, sharelatex_sid, project_id):
    project_URL="{base}/project/{pid}".format(base=BASE_URL,
                                            pid=project_id)

    get_project_data.project_data=None
    
    class Namespace(BaseNamespace):

        def on_connect(self):
            print('[Connected] Yeah !!')
        def on_reconnect(self):
            print('[Reconnected] re-Yeah !!')

        def on_disconnect(self):
            print('[Disconnected]  snif!  ')


    def on_joint_project(*args):
        get_project_data.project_data=args[1]

    def on_connection_accepted(*args):
        print('[connectionAccepted]  Waoh !!!')
        socketIO.emit('joinProject',{'project_id':project_id}, on_joint_project)

    def on_connection_rejected(*args):
        print('[connectionRejected]  oh !!!')

    with SocketIO('https://sharelatex.irisa.fr',
                        Namespace=Namespace, 
                        cookies={'sharelatex.sid': sharelatex_sid},
                        headers={'Referer': project_URL},) as socketIO :
        socketIO.on('connectionAccepted', on_connection_accepted)
        socketIO.on('connectionRejected', on_connection_rejected)
        socketIO.wait(seconds=1)

    return  get_project_data.project_data
# TEST of get project info

project_id='5d385b6f1693055a45f6e876'

client, login_data  = init_client()
r = client.post(LOGIN_URL, data=login_data, verify=False)
sharelatex_sid=r.cookies['sharelatex.sid']

project_data= get_project_data(client,login_data, sharelatex_sid, project_id)
print("project_data={}".format(project_data))




