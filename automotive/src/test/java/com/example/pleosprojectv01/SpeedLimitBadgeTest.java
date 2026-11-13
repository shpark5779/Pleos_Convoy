package com.example.pleosprojectv01;

import org.junit.Test;
import static org.junit.Assert.*;

public class SpeedLimitBadgeTest {
    private final double[][] points={{127,36},{127.001,36},{127.002,36}};
    @Test public void selectsPostedLimitAndUsesNewSectionAtBoundary() {
        int[][] roads={{0,0,50},{1,2,10}};
        assertEquals(Integer.valueOf(50),SpeedLimitBadge.resolve(points,roads,36,127.0005));
        assertEquals(Integer.valueOf(10),SpeedLimitBadge.resolve(points,roads,36,127.001));
        assertEquals(Integer.valueOf(10),SpeedLimitBadge.resolve(points,roads,36,127.0015));
    }
    @Test public void unknownAndOffRouteDoNotInventSpeedLimit() {
        assertNull(SpeedLimitBadge.resolve(points,new int[][]{{0,2,0}},36,127.0005));
        assertNull(SpeedLimitBadge.resolve(points,new int[0][0],36,127.0005));
        assertNull(SpeedLimitBadge.resolve(points,new int[][]{{0,2,50}},36.1,127));
    }
}
