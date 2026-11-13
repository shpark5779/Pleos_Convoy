package com.example.pleosprojectv01

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

class CompanionVehiclesTest {
    @Test fun onlyFreshOtherDriversAppear() {
        val members=JSONObject()
        fun add(id:String,age:Double=0.0,role:String="driver",lat:Double=36.35) {
            members.put(id,JSONObject().put("name",id).put("role",role).put("location",
                JSONObject().put("latitude",lat).put("longitude",127.38).put("measured_at",1000.0-age)))
        }
        add("self"); add("peer"); add("stale",31.0); add("future",-6.0)
        add("passenger",role="passenger"); add("invalid",lat=91.0)
        assertEquals(listOf("peer"),companionVehicles(JSONObject().put("members",members),"self",1000.0).map { it.id })
    }
    @Test fun movementAndExpiryAreReflected() {
        val point=JSONObject().put("latitude",36.35).put("longitude",127.38).put("measured_at",1000.0)
        val room=JSONObject().put("members",JSONObject().put("peer",JSONObject().put("name","B").put("location",point)))
        assertEquals(36.35,companionVehicles(room,"self",1000.0).single().latitude,0.000001)
        point.put("latitude",36.36)
        assertEquals(36.36,companionVehicles(room,"self",1003.0).single().latitude,0.000001)
        assertEquals(emptyList<CompanionVehicle>(),companionVehicles(room,"self",1031.0))
    }
    @Test fun missingCoordinatesDoNotAppear() {
        val room=JSONObject("{members:{peer:{location:{latitude:36.35}}}}")
        assertEquals(emptyList<CompanionVehicle>(),companionVehicles(room,"self",1000.0))
    }
}
