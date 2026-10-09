package com.xairca.backend.runs;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

/** Stored analyses. */
public interface AnalysisRunRepository extends JpaRepository<AnalysisRun, String> {

    List<AnalysisRun> findByCaseIdOrderByCreatedAtDesc(String caseId);

    List<AnalysisRun> findTop100ByOrderByCreatedAtDesc();

    List<AnalysisRun> findByBenchmarkJobId(String benchmarkJobId);
}
