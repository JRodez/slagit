Pull/Push sharelatex project from/to GIT


The code is currently experimental and under development.
Use it with caution.


Installation
------------


.. code:: bash

    # in the future ?
    pip install sharelatex

    # for now
    git clone https://gitlab.inria.fr/sed-rennes/sharelatex/python-sharelatex
    cd pyhton-sharelatex
    pip install [-e] .
       


Configuration
-------------

.. code:: bash

    echo '
    username: MYLOGIN
    password: MYPASSWORD
    ' > ~/.sharelatex.yaml

    chmod 600 ~/.sharelatex.yaml

Example
-------

Simple Workflow
~~~~~~~~~~~~~~~

.. code:: bash

    mkdir test
    cd test
    # download all files of a remote project
    git slatex init <project_id>
    # edit your files
    #
    # Push back your change to sharelatex
    # !!! this will overwrite any existing file in the sharelatex server with
    # your local changes
    git slatex push


Concurrent updates
~~~~~~~~~~~~~~~~~~

Concurrent updates may occur between your local files (because you changed them)
and the remote ones (because you collaborators changed them). Before pushing you
need to manually handle the case.


.. code:: bash

    # download all files of a remote project
    git slatex init <project_id>
    # edit your files
    #
    # resync you local files
    git checkout __remote__sharelatex__
    git slatex init <project id>
    # merge conflicting files
    git checkout master
    git slatex merge __remote__sharelatex__
    # resolve the conflicts and
    # Push back your change to sharelatex
    git slatex push
