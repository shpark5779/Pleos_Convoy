import unittest
from road_speed import RoadSpeedPlan


def route(limits):
    return {'segments':[[[127+i*.001,36.] for i in range(len(limits)+1)]],
            'roads':[{'start_index':i,'end_index':i,'limit_kph':v} for i,v in enumerate(limits)]}


class RoadSpeedTest(unittest.TestCase):
    def test_slows_before_lower_limit_and_never_exceeds_limit(self):
        for dt in (.25,1,2):
            plan=RoadSpeedPlan(route([50]*6+[10]*5))
            position=speed=0.;seen_low=False;braked_before=False
            boundary=plan.sections[1]['start_m']
            self.assertLess(plan.speed_cap(boundary-10)*3.6,50)
            self.assertAlmostEqual(plan.speed_cap(boundary)*3.6,10)
            for tick in range(int(400/dt)):
                position,speed=plan.advance(position,speed,dt,1,tick*dt)
                self.assertLessEqual(speed,plan.limit_at(position)+1e-7)
                if boundary-50<position<boundary and speed<15:braked_before=True
                if position>=boundary:seen_low=True
            self.assertTrue(seen_low)
            self.assertTrue(braked_before)

    def test_unknown_stops_and_is_not_a_default_limit(self):
        plan=RoadSpeedPlan(route([50,0,10]))
        position=speed=0.
        for tick in range(100):position,speed=plan.advance(position,speed,1,0,tick)
        self.assertLess(position,plan.sections[1]['start_m'])
        self.assertEqual(speed,0)
        self.assertIsNone(plan.limit_at(plan.sections[1]['start_m']+1))
        empty=RoadSpeedPlan({'segments':route([50])['segments'],'roads':[]})
        self.assertEqual(empty.advance(0,0,1,0,10),(0,0.0))

    def test_index_validation_boundary_and_independent_profiles(self):
        bad=route([50]);bad['roads'][0]['end_index']=9
        with self.assertRaises(ValueError):RoadSpeedPlan(bad)
        plan=RoadSpeedPlan(route([50,10]))
        self.assertEqual(plan.limit_at(plan.sections[1]['start_m']),10)
        wide=RoadSpeedPlan(route([50]*20))
        self.assertNotEqual(wide.advance(0,30,1,0,10)[1],wide.advance(0,30,1,1,10)[1])
        with self.assertRaises(ValueError):wide.advance(0,0,float('nan'),0,0)


if __name__=='__main__':unittest.main()
