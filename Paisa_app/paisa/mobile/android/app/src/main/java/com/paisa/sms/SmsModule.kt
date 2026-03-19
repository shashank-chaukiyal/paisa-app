// android/app/src/main/java/com/paisa/sms/SmsModule.kt
//
// Fix #7 (SMS hash alignment):
//   The field emitted to React Native is now named "localCacheKey"
//   instead of "hash" — aligning with SmsReceiver.kt and sms.ts.
//   This is a local cache key only; the server computes the authoritative
//   dedup hash as SHA-256(user_id:device_id:body).
//
// No other logic changes from the original.

package com.paisa.sms

import android.Manifest
import android.content.pm.PackageManager
import android.database.Cursor
import android.net.Uri
import android.util.Log
import androidx.core.content.ContextCompat
import com.facebook.react.bridge.*
import com.facebook.react.modules.core.PermissionAwareActivity
import com.facebook.react.modules.core.PermissionListener
import java.security.MessageDigest
import java.util.concurrent.TimeUnit

private const val TAG = "PaisaSmsModule"
private const val SMS_PERMISSION_REQUEST_CODE = 1001

class SmsModule(private val reactContext: ReactApplicationContext) :
    ReactContextBaseJavaModule(reactContext), PermissionListener {

    private var permissionPromise: Promise? = null

    override fun getName(): String = "PaisaSmsModule"

    init {
        SmsReceiver.reactContext = reactContext
        Log.i(TAG, "SmsModule initialized")
    }

    // ── Permissions ──────────────────────────────────────────────────

    @ReactMethod
    fun requestSmsPermission(promise: Promise) {
        val ctx = reactContext
        if (ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECEIVE_SMS)
            == PackageManager.PERMISSION_GRANTED
        ) {
            promise.resolve(true)
            return
        }

        permissionPromise = promise
        val activity = currentActivity as? PermissionAwareActivity ?: run {
            promise.reject("NO_ACTIVITY", "No activity available")
            return
        }
        activity.requestPermissions(
            arrayOf(Manifest.permission.RECEIVE_SMS, Manifest.permission.READ_SMS),
            SMS_PERMISSION_REQUEST_CODE,
            this,
        )
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<String>,
        grantResults: IntArray,
    ): Boolean {
        if (requestCode != SMS_PERMISSION_REQUEST_CODE) return false
        val granted = grantResults.all { it == PackageManager.PERMISSION_GRANTED }
        permissionPromise?.resolve(granted)
        permissionPromise = null
        return true
    }

    // ── Historical SMS import ─────────────────────────────────────────

    @ReactMethod
    fun readHistoricalSms(daysBack: Int, promise: Promise) {
        val safeDays = daysBack.coerceIn(1, 90)
        val cutoff = System.currentTimeMillis() - TimeUnit.DAYS.toMillis(safeDays.toLong())

        Thread {
            try {
                val results = WritableNativeArray()
                val uri = Uri.parse("content://sms/inbox")
                val projection = arrayOf("_id", "address", "body", "date")
                val selection = "date > ?"
                val selectionArgs = arrayOf(cutoff.toString())
                val sortOrder = "date DESC"

                val cursor: Cursor? = reactContext.contentResolver.query(
                    uri, projection, selection, selectionArgs, sortOrder
                )

                cursor?.use { c ->
                    val idxAddr = c.getColumnIndex("address")
                    val idxBody = c.getColumnIndex("body")
                    val idxDate = c.getColumnIndex("date")

                    while (c.moveToNext()) {
                        val sender = c.getString(idxAddr) ?: continue
                        val body   = c.getString(idxBody) ?: continue
                        val date   = c.getLong(idxDate)

                        val bodyLower = body.lowercase()
                        val isFinancial = listOf(
                            "debited", "credited", "rs.", "inr", "upi", "neft", "imps"
                        ).any { bodyLower.contains(it) }

                        if (!isFinancial) continue

                        val map = WritableNativeMap().apply {
                            putString("sender",       sender)
                            putString("body",         body)
                            // Fix #7: field renamed from "hash" to "localCacheKey"
                            // to clarify this is a local cache key only,
                            // NOT the server-side dedup hash.
                            putString("localCacheKey", sha256("$sender:$body"))
                            putDouble("timestamp",    date.toDouble())
                        }
                        results.pushMap(map)

                        if (results.size() >= 500) break
                    }
                }

                Log.i(TAG, "Historical SMS read: ${results.size()} messages")
                promise.resolve(results)

            } catch (e: Exception) {
                Log.e(TAG, "Failed to read historical SMS: ${e.message}")
                promise.reject("SMS_READ_ERROR", e.message)
            }
        }.start()
    }

    private fun sha256(input: String): String {
        val bytes = MessageDigest.getInstance("SHA-256").digest(input.toByteArray())
        return bytes.joinToString("") { "%02x".format(it) }
    }
}
