package com.cloud42labo.serendipityspot.data

import android.content.Context
import com.google.api.services.drive.Drive
import com.google.api.services.sheets.v4.Sheets
import com.google.api.services.sheets.v4.model.BatchUpdateSpreadsheetRequest
import com.google.api.services.sheets.v4.model.CellData
import com.google.api.services.sheets.v4.model.CellFormat
import com.google.api.services.sheets.v4.model.DeleteDimensionRequest
import com.google.api.services.sheets.v4.model.DimensionRange
import com.google.api.services.sheets.v4.model.ExtendedValue
import com.google.api.services.sheets.v4.model.Request
import com.google.api.services.sheets.v4.model.RowData
import com.google.api.services.sheets.v4.model.Sheet
import com.google.api.services.sheets.v4.model.SheetProperties
import com.google.api.services.sheets.v4.model.Spreadsheet
import com.google.api.services.sheets.v4.model.SpreadsheetProperties
import com.google.api.services.sheets.v4.model.TextFormat
import com.google.api.services.sheets.v4.model.UpdateCellsRequest
import com.google.api.services.sheets.v4.model.ValueRange
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.UUID

/**
 * ユーザー自身のGoogleドライブ上のスプレッドシートを「スポットDB」として扱うリポジトリ。
 *
 * 1行目はヘッダー、2行目以降が1スポット = 1行。
 * 列: id | lat | lng | title | memo | radiusMeters | createdAt
 */
class SheetsRepository(private val context: Context) {

    private val dateFormat = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ssXXX", Locale.JAPAN)

    /**
     * スプレッドシートIDを確定させる。
     * ローカルキャッシュ → Drive検索 → 新規作成、の順で解決する。
     */
    suspend fun ensureSpreadsheet(sheets: Sheets, drive: Drive): String = withContext(Dispatchers.IO) {
        SpotLocalCache.loadSpreadsheetId(context)?.let { cachedId ->
            val stillAccessible = runCatching { sheets.spreadsheets().get(cachedId).execute() }.isSuccess
            if (stillAccessible) return@withContext cachedId
        }

        val existing = findExistingSpreadsheet(drive)
        if (existing != null) {
            SpotLocalCache.saveSpreadsheetId(context, existing)
            return@withContext existing
        }

        val created = createSpreadsheet(sheets)
        SpotLocalCache.saveSpreadsheetId(context, created)
        created
    }

    private fun findExistingSpreadsheet(drive: Drive): String? {
        val query = "name = '$FILE_NAME' and mimeType = 'application/vnd.google-apps.spreadsheet' " +
            "and trashed = false and 'me' in owners"
        val result = drive.files().list()
            .setQ(query)
            .setSpaces("drive")
            .setFields("files(id, name)")
            .execute()
        return result.files?.firstOrNull()?.id
    }

    private fun createSpreadsheet(sheets: Sheets): String {
        val headerRow = RowData().setValues(
            listOf("id", "lat", "lng", "title", "memo", "radiusMeters", "createdAt").map { text ->
                CellData()
                    .setUserEnteredValue(ExtendedValue().setStringValue(text))
                    .setUserEnteredFormat(CellFormat().setTextFormat(TextFormat().setBold(true)))
            }
        )

        val spreadsheet = Spreadsheet()
            .setProperties(SpreadsheetProperties().setTitle(FILE_NAME))
            .setSheets(
                listOf(
                    Sheet().setProperties(SheetProperties().setTitle(SHEET_NAME))
                )
            )

        val created = sheets.spreadsheets().create(spreadsheet).execute()
        val sheetId = created.sheets[0].properties.sheetId

        val request = BatchUpdateSpreadsheetRequest().setRequests(
            listOf(
                Request().setUpdateCells(
                    UpdateCellsRequest()
                        .setStart(
                            com.google.api.services.sheets.v4.model.GridCoordinate()
                                .setSheetId(sheetId).setRowIndex(0).setColumnIndex(0)
                        )
                        .setRows(listOf(headerRow))
                        .setFields("userEnteredValue,userEnteredFormat.textFormat.bold")
                )
            )
        )
        sheets.spreadsheets().batchUpdate(created.spreadsheetId, request).execute()

        return created.spreadsheetId
    }

    suspend fun loadSpots(sheets: Sheets, spreadsheetId: String): List<Spot> = withContext(Dispatchers.IO) {
        val range = "$SHEET_NAME!A2:G"
        val response = sheets.spreadsheets().values().get(spreadsheetId, range).execute()
        val rows = response.getValues() ?: emptyList()

        val spots = rows.mapIndexedNotNull { index, row ->
            runCatching {
                Spot(
                    id = row.getOrNull(0)?.toString() ?: return@mapIndexedNotNull null,
                    lat = row.getOrNull(1)?.toString()?.toDouble() ?: return@mapIndexedNotNull null,
                    lng = row.getOrNull(2)?.toString()?.toDouble() ?: return@mapIndexedNotNull null,
                    title = row.getOrNull(3)?.toString() ?: "",
                    memo = row.getOrNull(4)?.toString() ?: "",
                    radiusMeters = row.getOrNull(5)?.toString()?.toFloatOrNull() ?: 150f,
                    rowIndex = index + 2,
                )
            }.getOrNull()
        }
        SpotLocalCache.save(context, spots)
        spots
    }

    suspend fun appendSpot(
        sheets: Sheets,
        spreadsheetId: String,
        lat: Double,
        lng: Double,
        title: String,
        memo: String,
        radiusMeters: Float = 150f,
    ): Spot = withContext(Dispatchers.IO) {
        val id = UUID.randomUUID().toString()
        val createdAt = dateFormat.format(Date())
        val row = listOf(id, lat, lng, title, memo, radiusMeters, createdAt)

        sheets.spreadsheets().values()
            .append(spreadsheetId, "$SHEET_NAME!A:G", ValueRange().setValues(listOf(row)))
            .setValueInputOption("USER_ENTERED")
            .setInsertDataOption("INSERT_ROWS")
            .execute()

        Spot(id, lat, lng, title, memo, radiusMeters)
    }

    /**
     * 名前とメモだけを書き換える。座標・id・作成日時は触らない。
     * [Spot.rowIndex] はシート読み込み時に振られた行番号で、ローカルキャッシュ由来の
     * ものは -1 になっている。その場合は更新できないので false を返す。
     */
    suspend fun updateSpotText(
        sheets: Sheets,
        spreadsheetId: String,
        spot: Spot,
        title: String,
        memo: String,
    ): Boolean = withContext(Dispatchers.IO) {
        if (spot.rowIndex < 2) return@withContext false
        val range = "$SHEET_NAME!D${spot.rowIndex}:E${spot.rowIndex}"
        sheets.spreadsheets().values()
            .update(spreadsheetId, range, ValueRange().setValues(listOf(listOf(title, memo))))
            .setValueInputOption("USER_ENTERED")
            .execute()
        true
    }

    /**
     * 行ごと削除する。以降の行番号がずれるため、呼び出し側は削除後に
     * [loadSpots] で読み直すこと。
     */
    suspend fun deleteSpot(
        sheets: Sheets,
        spreadsheetId: String,
        spot: Spot,
    ): Boolean = withContext(Dispatchers.IO) {
        if (spot.rowIndex < 2) return@withContext false
        val sheetId = sheetIdOf(sheets, spreadsheetId) ?: return@withContext false

        val request = BatchUpdateSpreadsheetRequest().setRequests(
            listOf(
                Request().setDeleteDimension(
                    DeleteDimensionRequest().setRange(
                        DimensionRange()
                            .setSheetId(sheetId)
                            .setDimension("ROWS")
                            // API は0始まり・終端排他。rowIndex は1始まりなので -1 する。
                            .setStartIndex(spot.rowIndex - 1)
                            .setEndIndex(spot.rowIndex)
                    )
                )
            )
        )
        sheets.spreadsheets().batchUpdate(spreadsheetId, request).execute()
        true
    }

    private fun sheetIdOf(sheets: Sheets, spreadsheetId: String): Int? {
        val spreadsheet = sheets.spreadsheets().get(spreadsheetId).execute()
        return spreadsheet.sheets
            ?.firstOrNull { it.properties?.title == SHEET_NAME }
            ?.properties?.sheetId
    }

    companion object {
        private const val FILE_NAME = "Serendipity Spot"
        private const val SHEET_NAME = "Spots"
    }
}
