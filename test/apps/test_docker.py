#
#    ICRAR - International Centre for Radio Astronomy Research
#    (c) UWA - The University of Western Australia, 2015
#    Copyright by UWA (in the framework of the ICRAR)
#    All rights reserved
#
#    This library is free software; you can redistribute it and/or
#    modify it under the terms of the GNU Lesser General Public
#    License as published by the Free Software Foundation; either
#    version 2.1 of the License, or (at your option) any later version.
#
#    This library is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#    Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public
#    License along with this library; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston,
#    MA 02111-1307  USA
#

import os
import shutil
import tempfile
import unittest
import warnings

from configobj import ConfigObj
from docker.client import AutoVersionClient
from docker.errors import DockerException

from dfms import droputils
from dfms.apps.dockerapp import DockerApp
from dfms.drop import FileDROP, NgasDROP
from dfms.droputils import DROPWaiterCtx
import six


class DockerTests(unittest.TestCase):
    _temp = None

    @classmethod
    def setUpClass(cls):
        config_file_name = os.path.join(os.path.expanduser('~'), '.dfms/dfms.settings')
        if os.path.exists(config_file_name):
            config = ConfigObj(config_file_name)
            DockerTests._temp = config.get('OS_X_TEMP')

            if not os.path.exists(DockerTests._temp):
                os.makedirs(DockerTests._temp)

        if DockerTests._temp is None:
            DockerTests._temp = '/tmp/sdp_dfms'


    def tearDown(self):
        shutil.rmtree("/tmp/sdp_dfms", True)

    def test_simpleCopy(self):
        """
        Simple test for a dockerized application. It copies the contents of one
        file into another via the command-line cp utility. It then checks that
        the contents of the target DROP are correct, and that the target file is
        actually owned by our process.

        The test will not run if a docker daemon cannot be contacted though;
        this is to avoid failures in machines that don't have a docker service
        running.
        """

        try:
            AutoVersionClient().close()
        except DockerException:
            warnings.warn("Cannot contact the Docker daemon, skipping docker tests")
            return

        a = FileDROP('a', 'a')
        b = DockerApp('b', 'b', image='ubuntu:14.04', command='cp %i0 %o0')
        c = FileDROP('c', 'c')

        b.addInput(a)
        b.addOutput(c)

        # Random data so we always check different contents
        data = os.urandom(10)
        with DROPWaiterCtx(self, c, 100):
            a.write(data)
            a.setCompleted()

        self.assertEqual(data, droputils.allDropContents(c))

        # We own the file, not root
        uid = os.getuid()
        self.assertEqual(uid, os.stat(c.path).st_uid)

    def test_clientServer(self):
        """
        A client-server duo. The server outputs the data it receives to its
        output DROP, which in turn is the data held in its input DROP. The graph
        looks like this:

        A --|--> B(client) --|--> D
            |--> C(server) --|

        C is a server application which B connects to. Therefore C must be
        started before B, so B knows C's IP address and connects successfully.
        Although the real writing is done by C, B in this example is also
        treated as a publisher of D. This way D waits for both applications to
        finish before proceeding.
        """
        try:
            AutoVersionClient().close()
        except DockerException:
            warnings.warn("Cannot contact the Docker daemon, skipping docker tests")
            return

        a = FileDROP('a', 'a')
        b = DockerApp('b', 'b', image='ubuntu:14.04', command='cat %i0 > /dev/tcp/%containerIp[c]%/8000')
        c = DockerApp('c', 'c', image='ubuntu:14.04', command='nc -l 8000 > %o0')
        d = FileDROP('d', 'd')

        b.addInput(a)
        b.addOutput(d)
        c.addInput(a)
        c.addOutput(d)

        # Let 'b' handle its interest in c
        b.handleInterest(c)

        data = os.urandom(10)
        with DROPWaiterCtx(self, d, 100):
            a.write(data)
            a.setCompleted()

        self.assertEqual(data, droputils.allDropContents(d))

    def test_quotedCommands(self):
        """
        A test to check that commands using quotes are correctly executed, which
        means that their quotes were correctly escaped when the final docker
        command was executed
        """

        def assertMsgIsCorrect(msg, command):
            a = DockerApp('a', 'a', image='ubuntu:14.04', command=command)
            b = FileDROP('b','b')
            a.addOutput(b)
            with DROPWaiterCtx(self, b, 100):
                a.execute()
            self.assertEqual(six.b(msg), droputils.allDropContents(b))

        msg = "This is a message with a single quote: '"
        assertMsgIsCorrect(msg, 'echo -n "{0}" > %o0'.format(msg))
        msg = 'This is a message with a double quotes: "'
        assertMsgIsCorrect(msg, "echo -n '{0}' > %o0".format(msg))

    def test_dataURLReference(self):
        """
        A test to check that DROPs other than FileDROPs and DirectoryContainers
        can pass their dataURLs into docker containers
        """
        self._ngas_and_fs_io("echo -n '%iDataURL0' > %o0")

    def test_refer_to_io_by_uid(self):
        """
        A test to check that input and output Drops can be referred to by their
        UIDs (in addition to their position in the list of inputs or outputs)
        in the command-line.
        """
        self._ngas_and_fs_io("echo -n '%iDataURL[a]' > %o[c]")

    def _ngas_and_fs_io(self, command):
        a = NgasDROP('a', 'a') # not a filesystem-related DROP, we can reference its URL in the command-line
        b = DockerApp('b', 'b', image="ubuntu:14.04", command=command)
        c = FileDROP('c', 'c')
        b.addInput(a)
        b.addOutput(c)
        with DROPWaiterCtx(self, b, 100):
            a.setCompleted()
        self.assertEqual(six.b(a.dataURL), droputils.allDropContents(c))


    def test_additional_bindings(self):

        # Some additional stuff to bind into docker
        tempDir  = tempfile.mkdtemp()
        tempFile = tempfile.mktemp()
        with open(tempFile, 'w') as f:
            f.write('data')

        # One binding specifies the target path in the container, the other doesn't
        # so it defaults to the same path
        a = DockerApp(
                'a',
                'a',
                image='ubuntu:14.04',
                command="cp /opt/file %s" % (tempDir,),
                additionalBindings=[tempDir, "%s:/opt/file" % (tempFile,)]
        )
        a.execute()

        # We copied the file into the directory, but since in the container the
        # file was called "file" we'll see it with that name in tempDir
        self.assertEqual(1, len(os.listdir(tempDir)))
        with open(os.path.join(tempDir, 'file')) as f:
            data = f.read()
        self.assertEqual('data', data)

        # Cleanup
        os.unlink(tempFile)
        shutil.rmtree(tempDir)
