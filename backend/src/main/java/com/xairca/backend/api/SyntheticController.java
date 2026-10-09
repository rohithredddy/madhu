package com.xairca.backend.api;

import com.xairca.backend.cases.CaseSummary;
import com.xairca.backend.synthetic.SyntheticService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

/** POST /api/synthetic: generate a case in the lab and add it to the catalog. */
@RestController
public class SyntheticController {

    private final SyntheticService synthetic;

    public SyntheticController(SyntheticService synthetic) {
        this.synthetic = synthetic;
    }

    @PostMapping("/api/synthetic")
    public CaseSummary generate(@RequestBody SyntheticService.Settings settings) {
        return synthetic.generate(settings);
    }
}
