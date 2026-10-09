package com.xairca.backend.api;

import com.xairca.backend.replay.ReplayService;
import com.xairca.backend.replay.ReplayState;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import java.util.Map;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Replay: play a case as if live, watch the detector, see the explanation. */
@RestController
@RequestMapping("/api/replay")
public class ReplayController {

    private final ReplayService replay;

    public ReplayController(ReplayService replay) {
        this.replay = replay;
    }

    public record StartBody(@NotBlank String caseId, int speed, String engine) {}

    @PostMapping
    public Map<String, String> start(@Valid @RequestBody StartBody body) {
        return Map.of("sessionId", replay.start(body.caseId(), body.speed(), body.engine()));
    }

    @GetMapping("/{sessionId}")
    public ReplayState state(@PathVariable String sessionId,
                             @RequestParam(defaultValue = "false") boolean showGroundTruth) {
        return replay.state(sessionId, showGroundTruth);
    }

    @DeleteMapping("/{sessionId}")
    public ResponseEntity<Void> stop(@PathVariable String sessionId) {
        replay.stop(sessionId);
        return ResponseEntity.noContent().build();
    }
}
