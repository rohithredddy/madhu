package com.xairca.backend.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.xairca.backend.cases.CaseSummary;
import com.xairca.backend.cases.ColumnInfo;
import com.xairca.backend.common.BadRequestException;
import com.xairca.backend.upload.UploadService;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestPart;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;

/** Upload a user's own CSV as a case (docs/03 section 4.11). */
@RestController
@RequestMapping("/api/uploads")
public class UploadController {

    private final UploadService uploads;
    private final ObjectMapper mapper;

    public UploadController(UploadService uploads, ObjectMapper mapper) {
        this.uploads = uploads;
        this.mapper = mapper;
    }

    /** Multipart: {@code file} (the CSV) and {@code meta} (JSON, see UploadService.UploadMeta). */
    @PostMapping(consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public CaseSummary upload(@RequestPart("file") MultipartFile file, @RequestPart("meta") String meta)
            throws IOException {
        UploadService.UploadMeta parsed;
        try {
            parsed = mapper.readValue(meta, UploadService.UploadMeta.class);
        } catch (IOException e) {
            throw new BadRequestException("the meta part is not valid JSON: " + e.getMessage());
        }
        return uploads.upload(new String(file.getBytes(), StandardCharsets.UTF_8), parsed);
    }

    /** {@code {"header": "time,a_cpu,..."}} -> a proposed column map for the user to check. */
    @PostMapping("/guess-columns")
    public List<ColumnInfo> guess(@RequestBody Map<String, String> body) {
        String header = body.get("header");
        if (header == null || header.isBlank()) {
            throw new BadRequestException("send the CSV header line as \"header\"");
        }
        return uploads.guessColumns(header);
    }
}
