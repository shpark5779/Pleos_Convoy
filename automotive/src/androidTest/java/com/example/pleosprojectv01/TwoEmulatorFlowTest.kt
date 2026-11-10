package com.example.pleosprojectv01

import android.content.Intent
import android.util.Log
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.click
import androidx.test.espresso.action.ViewActions.scrollTo
import androidx.test.espresso.matcher.ViewMatchers.withText
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.hamcrest.Matchers.containsString
import org.json.JSONObject
import org.junit.Assert.*
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Run on two devices concurrently using server/test_two_emulators.py. */
@RunWith(AndroidJUnit4::class)
class TwoEmulatorFlowTest {
    private fun await(message: String, predicate: () -> Boolean) {
        val deadline = System.currentTimeMillis() + 90000
        while (System.currentTimeMillis() < deadline) {
            if (predicate()) return
            Thread.sleep(300)
        }
        fail(message)
    }

    @Test
    fun bothDevicesShareApproveAndApply() {
        val args = InstrumentationRegistry.getArguments()
        assumeTrue("Requires the two-device orchestrator", args.containsKey("convoy_role"))
        val role = args.getString("convoy_role")!!
        val session = ConvoySession("http://10.0.2.2:8765", args.getString("convoy_code")!!,
            args.getString("convoy_member")!!, args.getString("convoy_token")!!)
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        val context = instrumentation.targetContext
        context.getSharedPreferences("convoy", 0).edit().putString("server", session.server)
            .putString("code", session.code).putString("member_id", session.memberId)
            .putString("token", session.token).commit()
        instrumentation.startActivitySync(Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        val latitude = if (role == "owner") 37.5665 else 36.3504
        val longitude = if (role == "owner") 126.9780 else 127.3845
        onView(withText("실제 차량 위치 공유")).perform(scrollTo(), click())
        await("Both device locations must be shared") {
            val members = ConvoyApi.room(session).getJSONObject("members")
            members.keys().asSequence().all { members.getJSONObject(it).optJSONObject("location") != null }
        }
        val ownLocation = ConvoyApi.room(session).getJSONObject("members").getJSONObject(session.memberId).getJSONObject("location")
        assertEquals("sdk", ownLocation.getString("source"))
        assertEquals(latitude, ownLocation.getDouble("latitude"), 0.00001)
        assertEquals(longitude, ownLocation.getDouble("longitude"), 0.00001)
        if (role == "owner") {
            onView(withText("실제 장소 검색 (TMAP)")).perform(scrollTo(), click())
            onView(withText("휴게소 후보 찾기")).perform(scrollTo(), click())
            await("Candidate not displayed") {
                runCatching { onView(withText(containsString("휴게소 테스트 1"))).perform(scrollTo(), click()) }.isSuccess
            }
            onView(withText("제안 보내기")).perform(click())
        } else {
            await("Proposal alert not displayed on peer device") {
                runCatching { onView(withText("승인")).perform(click()) }.isSuccess
            }
        }
        await("Both drivers must approve") { ConvoyApi.room(session).optJSONObject("proposal")?.optString("status") == "approved" }
        await("Apply button not displayed") {
            runCatching { onView(withText("내 앱 경로에 반영")).perform(scrollTo(), click()) }.isSuccess
        }
        onView(withText("경로 변경 요청")).perform(click())
        var receipt = JSONObject()
        await("SDK result was not reported") {
            receipt = ConvoyApi.room(session).getJSONObject("proposal").getJSONObject("applications").getJSONObject(session.memberId)
            receipt.optString("state") in listOf("succeeded", "failed", "unconfirmed")
        }
        assertTrue(receipt.has("attempt_id"))
        assertEquals(receipt.optString("detail"), "succeeded", receipt.optString("state"))
        Log.i("TwoEmulatorCheck", "$role receipt: ${receipt.optString("state")} / ${receipt.optString("detail")}")
    }
}
