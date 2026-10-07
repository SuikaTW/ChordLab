import copy
import unittest
from app.chord_review import validate_proposal,merge_local


class ProposalTests(unittest.TestCase):
    def setUp(self):
        self.original=[dict(start=0,end=2,chord='C',manual=True),dict(start=2,end=8,chord='C'),dict(start=8,end=10,chord='G')]
        self.proposal=[copy.deepcopy(self.original[0]),dict(start=2,end=3,chord='C'),dict(start=3,end=7,chord='Am'),dict(start=7,end=8,chord='C'),copy.deepcopy(self.original[-1])]
    def test_valid_local_split_preserves_coverage_and_manual_metadata(self):
        self.assertEqual(validate_proposal(self.proposal,self.original,3,7,10),self.proposal)
    def test_missing_outside_changed_manual_and_overlapping_segments_are_rejected(self):
        for mutation in ('outside','manual','overlap','missing'):
            data=copy.deepcopy(self.proposal)
            if mutation=='outside':data[-1]['chord']='Am'
            if mutation=='manual':data[0]['manual']=False
            if mutation=='overlap':data[2]['start']=2.9
            if mutation=='missing':data.pop(2)
            with self.assertRaises(ValueError):validate_proposal(data,self.original,3,7,10)
    def test_invalid_labels_times_and_oversized_payload_are_rejected(self):
        for key,value in [('chord','x'*25),('chord',None),('start',float('nan')),('start',True),('end',20)]:
            data=copy.deepcopy(self.proposal);data[2][key]=value
            with self.assertRaises(ValueError):validate_proposal(data,self.original,3,7,10)
        with self.assertRaises(ValueError):validate_proposal(self.proposal*200,self.original,3,7,10)
    def test_original_manual_tail_margin_is_preserved_not_silently_clipped(self):
        source=[dict(start=0,end=10.1,chord='C',manual=True)]
        clipped=[dict(start=0,end=10,chord='C',manual=True)]
        result=merge_local(source,clipped,3,7)
        self.assertEqual(result,source)
        self.assertEqual(validate_proposal(result,source,3,7,10),source)


if __name__=='__main__':unittest.main()
