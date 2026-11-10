package com.example.pleosprojectv01

import android.content.Intent
import android.util.Log
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.action.ViewActions.scrollTo
import androidx.test.espresso.matcher.ViewMatchers.withText
import androidx.test.espresso.matcher.ViewMatchers.isDisplayed
import androidx.test.espresso.assertion.ViewAssertions.matches
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.hamcrest.Matchers.containsString
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ConvoyFlowTest {
    private val server = "http://10.0.2.2:8765"
    private fun point(name: String, lat: Double, lon: Double) = JSONObject().put("name", name)
        .put("latitude", lat).put("longitude", lon).put("source", "demo")

    private fun await(message: String, predicate: () -> Boolean) {
        val deadline = System.currentTimeMillis() + 15000
        while (System.currentTimeMillis() < deadline) {
            if (predicate()) return
            Thread.sleep(200)
        }
        fail(message)
    }

    @Test
    fun twoVehiclesProposeApproveAndReceiveRealNavigationResult() {
        val destination = point("테스트 목적지", 37.48544722, 127.03636666)
        val ownerReply = ConvoyApi.request(server, "/rooms", JSONObject().put("name", "차량 A · 화면 검증").put("destination", destination))
        val code = ownerReply.getString("code")
        val owner = ConvoySession(server, code, ownerReply.getString("member_id"), ownerReply.getString("token"))
        val peerReply = ConvoyApi.request(server, "/rooms/$code/join", JSONObject().put("name", "차량 B · 테스트"))
        val peer = ConvoySession(server, code, peerReply.getString("member_id"), peerReply.getString("token"))
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        context.getSharedPreferences("convoy", 0).edit().putString("server", server).putString("code", code)
            .putString("member_id", owner.memberId).putString("token", owner.token).commit()
        fun peerLocation() = ConvoyApi.room(peer, "location", JSONObject().put("latitude", 37.40)
            .put("longitude", 127.09).put("measured_at", System.currentTimeMillis() / 1000.0).put("source", "demo"))
        peerLocation()
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            onView(withText("테스트 위치 공유 (실제 GPS 아님)")).perform(scrollTo(), click())
            await("앱의 위치가 서버에 전송되지 않음") {
                ConvoyApi.room(owner).getJSONObject("members").getJSONObject(owner.memberId).optJSONObject("location") != null
            }
            peerLocation()
            onView(withText("휴게소 후보 찾기")).perform(scrollTo(), click())
            Thread.sleep(1500)
            onView(withText(containsString("휴게소 테스트 1"))).perform(scrollTo(), click())
            onView(withText("제안 보내기")).perform(click())
            await("제안이 등록되지 않음") { ConvoyApi.room(peer).optJSONObject("proposal") != null }
            val pending = ConvoyApi.room(peer).getJSONObject("proposal")
            assertEquals("pending", pending.getString("status"))
            assertEquals("not_requested", pending.getJSONObject("applications").getJSONObject(owner.memberId).getString("state"))
            val id = pending.getString("id")
            ConvoyApi.room(peer, "decisions", JSONObject().put("proposal_id", id).put("approve", true))
            Thread.sleep(4000)
            onView(withText("내 내비에 반영")).perform(scrollTo(), click())
            onView(withText("경로 변경 요청")).perform(click())
            val deadline = System.currentTimeMillis() + 55000
            var receipt = JSONObject()
            while (System.currentTimeMillis() < deadline) {
                receipt = ConvoyApi.room(owner).getJSONObject("proposal").getJSONObject("applications").getJSONObject(owner.memberId)
                if (receipt.optString("state") in listOf("succeeded", "failed", "unconfirmed")) break
                Thread.sleep(500)
            }
            assertTrue("요청이 실제 SDK 결과 또는 확인 불가로 끝나야 함", receipt.optString("state") in listOf("succeeded", "failed", "unconfirmed"))
            Log.i("ConvoyCheck", "Real Navigation receipt: ${receipt.optString("state")} / ${receipt.optString("detail")}")
            // Exercise the actual Android action dispatch, without approving or changing a route.
            context.startActivity(Intent("SHOW_CONVOY_STATUS").setPackage(context.packageName).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            Thread.sleep(1500)
            onView(withText("같이 가요")).check(matches(isDisplayed()))
    }
}
