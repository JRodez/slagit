WORK IN PROGRESS: Pull/Push sharelatex project from/to GIT

The code is currently experimental and under development.
Use it with caution.


Installation
------------


.. code:: bash

    # Latest stable version
    pip install sharelatex

    # Development version
    git clone https://gitlab.inria.fr/sed-rennes/sharelatex/python-sharelatex
    cd python-sharelatex
    pip install [-e] .


Example
-------

Get an existing project on slatex
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: bash

    mkdir test
    cd test
    # download all files of a remote project
    git slatex clone <project_URL> <local_path_to_project>


Editing and pushing back to slatex
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


.. code:: bash

    # edit your files
    # commit, commit, commit ...
    #
    # Push back your change to sharelatex
    git slatex push

Pull changes from sharelatex to local (like a git pull)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~


.. code:: bash
    # Pull changes from sharelatex
    git slatex pull


Concurrent updates may occur between your local files (because you changed them)
and the remote ones (because you collaborators changed them). So before pushing,
we try to make sure the merge between the remote copy and the local ones is ok.
You'll have to resolve the conflict manually (as usual with Git) and attempt a
new push.

Create a remote project from a local git
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: bash
   
   git slatex new <base_server_URL> <new_project_name>
