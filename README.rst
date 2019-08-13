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

Get an existing project on slatex
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: bash

    mkdir test
    cd test
    # download all files of a remote project
    git slatex init <project_id>
    # edit your files
    #
    # Push back your change to sharelatex
    git slatex push


Concurrent updates may occur between your local files (because you changed them)
and the remote ones (because you collaborators changed them).
So before pushing, we try to make sure the merge between the remote copy and the
local ones is ok.

Create a remote project from a local git
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code:: bash
   
   git slatex new <name>
