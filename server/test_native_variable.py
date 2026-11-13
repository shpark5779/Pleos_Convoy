import unittest
from demo_native_variable import speed_kph


class VariableSpeedTest(unittest.TestCase):
    def test_independent_bounded_speeds_stops_and_recovery(self):
        profiles=[[speed_kph(i,t/10) for t in range(900)] for i in range(2)]
        self.assertTrue(all(0<=s<60 for p in profiles for s in p))
        self.assertNotEqual(profiles[0],profiles[1])
        for i in range(2):
            self.assertEqual(speed_kph(i,0),0)
            self.assertGreater(max(profiles[i]),35)
            self.assertEqual(speed_kph(i,32-i*17),0)
            self.assertGreater(speed_kph(i,45),0)
            self.assertGreater(len(set(round(s) for s in profiles[i])),20)


if __name__=='__main__':unittest.main()
