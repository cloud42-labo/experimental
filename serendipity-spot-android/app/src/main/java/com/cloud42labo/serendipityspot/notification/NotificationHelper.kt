package com.cloud42labo.serendipityspot.notification

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import android.os.VibrationEffect
import android.os.Vibrator
import android.os.VibratorManager
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.cloud42labo.serendipityspot.MainActivity
import com.cloud42labo.serendipityspot.R
import com.cloud42labo.serendipityspot.data.Spot

object NotificationHelper {
    private const val CHANNEL_ID = "serendipity_spot_proximity"
    private val VIBRATE_PATTERN = longArrayOf(0, 500, 200, 500)

    fun ensureChannel(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java)
        val channel = NotificationChannel(
            CHANNEL_ID,
            context.getString(R.string.notification_channel_name),
            NotificationManager.IMPORTANCE_HIGH
        ).apply {
            description = context.getString(R.string.notification_channel_desc)
            enableVibration(true)
            vibrationPattern = VIBRATE_PATTERN
        }
        manager.createNotificationChannel(channel)
    }

    fun notifyNearby(context: Context, spot: Spot) {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) !=
            PackageManager.PERMISSION_GRANTED
        ) {
            return
        }

        vibrate(context)

        val contentIntent = Intent(context, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            putExtra(MainActivity.EXTRA_FOCUS_SPOT_ID, spot.id)
        }
        val pendingIntent = PendingIntent.getActivity(
            context,
            spot.id.hashCode(),
            contentIntent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )

        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setContentTitle("Serendipity Spot: ${spot.title}")
            .setContentText(spot.memo.ifBlank { "近くに来ました！" })
            .setStyle(NotificationCompat.BigTextStyle().bigText(spot.memo.ifBlank { "近くに来ました！" }))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setAutoCancel(true)
            .setContentIntent(pendingIntent)
            .setVibrate(VIBRATE_PATTERN)
            .build()

        NotificationManagerCompat.from(context).notify(spot.id.hashCode(), notification)
    }

    private fun vibrate(context: Context) {
        val vibrator = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            val manager = context.getSystemService(VibratorManager::class.java)
            manager.defaultVibrator
        } else {
            @Suppress("DEPRECATION")
            context.getSystemService(Context.VIBRATOR_SERVICE) as Vibrator
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            vibrator.vibrate(VibrationEffect.createWaveform(VIBRATE_PATTERN, -1))
        } else {
            @Suppress("DEPRECATION")
            vibrator.vibrate(VIBRATE_PATTERN, -1)
        }
    }
}
