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
'''
Created on 22 Jun 2015

@author: rtobar
'''

import os
import shutil
import time
import unittest
from unittest.case import TestCase

from dfms import data_object
from dfms.ddap_protocol import DROPStates, DROPPhases
from dfms.lifecycle import dlm


class TestDataLifecycleManager(TestCase):

    def tearDown(self):
        shutil.rmtree("/tmp/sdp_dfms", True)
        shutil.rmtree("/tmp/sdp-hsm", True)

    def _writeAndClose(self, dataObject):
        '''
        :param dfms.data_object.AbstractDROP dataObject:
        '''
        dataObject.write(' ')
        # all DROPs submitted to this method have expectedSize=1, so this
        # will trigger the change to COMPLETED

    def test_basicCreation(self):
        manager = dlm.DataLifecycleManager()
        manager.startup()
        manager.cleanup()

    def test_dataObjectAddition(self):
        with dlm.DataLifecycleManager() as manager:
            dataObject = data_object.FileDROP('oid:A', 'uid:A1', expectedSize=10)
            manager.addDataObject(dataObject)

    def test_dataObjectCompleteTriggersReplication(self):
        with dlm.DataLifecycleManager() as manager:
            dataObject = data_object.FileDROP('oid:A', 'uid:A1', expectedSize=1)
            manager.addDataObject(dataObject)
            self._writeAndClose(dataObject)

            # The call to close() should have turned it into a SOLID object
            # because the DLM replicated it
            self.assertEquals(DROPPhases.SOLID, dataObject.phase)
            self.assertEquals(2, len(manager.getDataObjectUids(dataObject)))

            # Try the same with a non-precious data object, it shouldn't be replicated
            dataObject = data_object.FileDROP('oid:B', 'uid:B1', expectedSize=1, precious=False)
            manager.addDataObject(dataObject)
            self._writeAndClose(dataObject)
            self.assertEquals(DROPPhases.GAS, dataObject.phase)
            self.assertEquals(1, len(manager.getDataObjectUids(dataObject)))

    def test_expiringNormalDataObject(self):

        with dlm.DataLifecycleManager(checkPeriod=0.5) as manager:
            dataObject = data_object.FileDROP('oid:A', 'uid:A1', expectedSize=1, lifespan=0.5)
            manager.addDataObject(dataObject)

            # Writing moves the DROP to COMPLETE
            self._writeAndClose(dataObject)

            # Wait now, the DROP should be moved by the DLM to EXPIRED
            time.sleep(1)

            self.assertEquals(DROPStates.EXPIRED, dataObject.status)


    def test_lostDataObject(self):
        with dlm.DataLifecycleManager(checkPeriod=0.5) as manager:
            do = data_object.FileDROP('oid:A', 'uid:A1', expectedSize=1, lifespan=10, precious=False)
            manager.addDataObject(do)
            self._writeAndClose(do)

            # "externally" remove the file, its contents now don't exist
            os.unlink(do._fnm)

            # Let the DLM do its work
            time.sleep(1)

            # Check that the DROP is marked as LOST
            self.assertEquals(DROPPhases.LOST, do.phase)

    def test_cleanupExpiredDataObjects(self):
        with dlm.DataLifecycleManager(checkPeriod=0.5, cleanupPeriod=2) as manager:
            do = data_object.FileDROP('oid:A', 'uid:A1', expectedSize=1, lifespan=1, precious=False)
            manager.addDataObject(do)
            self._writeAndClose(do)

            # Wait 2 seconds, the DROP is still COMPLETED
            time.sleep(0.5)
            self.assertEquals(DROPStates.COMPLETED, do.status)
            self.assertTrue(do.exists())

            # Wait 5 more second, now it should be expired but still there
            time.sleep(1)
            self.assertEquals(DROPStates.EXPIRED, do.status)
            self.assertTrue(do.exists())

            # Wait 2 more seconds, now it should have been deleted
            time.sleep(1)
            self.assertEquals(DROPStates.DELETED, do.status)
            self.assertFalse(do.exists())

if __name__ == '__main__':
    unittest.main()