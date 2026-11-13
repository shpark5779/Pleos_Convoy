"""SDK RoadInfo speed limits, indexed on the SDK's own route vertices (km/h)."""
import bisect
import math

from tmap_service import km


class RoadSpeedPlan:
    def __init__(self, route):
        if len(route.get('segments', [])) != 1:
            raise ValueError('SDK vertex indices require one coordinate list')
        points = route['segments'][0]
        if len(points) < 2:
            raise ValueError('SDK route coordinates missing')
        self.distances = [0.0]
        for a, b in zip(points, points[1:]):
            self.distances.append(self.distances[-1] + 1000*km(
                {'longitude':a[0], 'latitude':a[1]}, {'longitude':b[0], 'latitude':b[1]}))
        roads = route.get('roads', [])
        for road in roads:
            if not 0 <= road['start_index'] <= road['end_index'] < len(points):
                raise ValueError('RoadInfo index does not match SDK coordinates')
        self.sections = []
        for index in range(len(points)-1):
            limits = [r.get('limit_kph') for r in roads if r['start_index'] <= index <= r['end_index']]
            limit = min(limits) if limits and all(isinstance(v, (int,float)) and math.isfinite(v) and 0<v<=240 for v in limits) else None
            start, end = self.distances[index:index+2]
            if self.sections and self.sections[-1]['limit_kph'] == limit:
                self.sections[-1]['end_m'] = end
            else:
                self.sections.append({'start_m':start, 'end_m':end, 'limit_kph':limit})
        self.total = self.distances[-1]

    def limit_at(self, distance):
        for section in self.sections:
            if distance < section['end_m']-1e-8:
                return section['limit_kph']
        return self.sections[-1]['limit_kph']

    def speed_cap(self, distance):
        limit = self.limit_at(distance)
        if limit is None:
            return 0.0
        cap = limit/3.6
        # Lower future limits and unknown sections are anticipated, not handled after entry.
        for section in self.sections:
            if section['start_m'] <= distance:
                continue
            next_speed = (section['limit_kph'] or 0)/3.6
            remaining = max(0,section['start_m']-distance-.5)
            cap = min(cap,math.sqrt(next_speed**2 + 2*1.5*remaining))
        cap = min(cap,math.sqrt(2*1.5*max(0,self.total-distance-.5)))
        return cap

    def advance(self, distance, speed_kph, dt, vehicle, elapsed):
        if not all(math.isfinite(x) for x in (distance,speed_kph,dt,elapsed)) or dt<0 or speed_kph<0 or distance<0:
            raise ValueError('Invalid driving state')
        limit = self.limit_at(distance)
        if limit is None or distance >= self.total-.5:
            return distance,0.0
        # Different driver profiles, expressed as a fraction of the actual posted limit.
        factor = (.88+.07*math.sin(elapsed/9)) if vehicle==0 else (.78+.08*math.sin(elapsed/13+1))
        phase = (elapsed+vehicle*17)%70
        stop = min(1,max(0,elapsed)/6)
        if 30<=phase<35: stop=0
        elif 25<=phase<30: stop*=max(0,(30-phase)/5)
        elif 35<=phase<40: stop*=min(1,(phase-35)/5)
        current = speed_kph/3.6
        target = limit/3.6*factor*stop
        speed = min(target,current+1.2*dt,self.speed_cap(distance+current*dt))
        position = min(self.total,distance+(current+speed)*.5*dt)
        # Unknown data is a stop, never an assumed speed limit.
        for section in self.sections:
            if section['limit_kph'] is None and section['start_m']>distance:
                position=min(position,max(distance,section['start_m']-.5))
        actual_limit = self.limit_at(position)
        speed = min(speed,(actual_limit or 0)/3.6)
        return position,speed*3.6
