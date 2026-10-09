package com.xairca.backend.runs;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Index;
import jakarta.persistence.Lob;
import jakarta.persistence.Table;
import java.time.Instant;

/**
 * One stored analysis (docs/03 section 6). The full engine response and the
 * explanation are kept as JSON; the fields a list or a benchmark needs to count -
 * verdict, top answers, correctness - are columns of their own so they can be
 * queried without parsing JSON.
 */
@Entity
@Table(name = "analysis_run", indexes = {
        @Index(name = "idx_run_case", columnList = "caseId"),
        @Index(name = "idx_run_job", columnList = "benchmarkJobId")})
public class AnalysisRun {

    @Id
    private String id;
    private Instant createdAt;
    private String caseId;
    private String engine;
    /** ONE_CLICK, REPLAY or BENCHMARK. */
    private String mode;
    private int delaySeconds;
    private Long alarmTimeSec;
    private Double changePointSec;
    /** ROOT_CAUSE_FOUND or NO_CLEAR_CAUSE. */
    private String verdict;
    private String top1Service;
    private String top1Indicator;
    private String confidence;
    private Integer rankGtService;
    private Integer rankGtIndicator;
    private Boolean correctTop1;
    private Boolean correctTop3;
    private Boolean symptomError;
    private long tookMs;
    private String benchmarkJobId;

    @Lob
    @Column(columnDefinition = "CLOB")
    private String responseJson;

    @Lob
    @Column(columnDefinition = "CLOB")
    private String explanationJson;

    @Lob
    @Column(columnDefinition = "CLOB")
    private String warnings;

    protected AnalysisRun() {}

    public AnalysisRun(String id, Instant createdAt, String caseId, String engine, String mode,
                       int delaySeconds) {
        this.id = id;
        this.createdAt = createdAt;
        this.caseId = caseId;
        this.engine = engine;
        this.mode = mode;
        this.delaySeconds = delaySeconds;
    }

    public String getId() { return id; }
    public Instant getCreatedAt() { return createdAt; }
    public String getCaseId() { return caseId; }
    public String getEngine() { return engine; }
    public void setEngine(String engine) { this.engine = engine; }
    public String getMode() { return mode; }
    public int getDelaySeconds() { return delaySeconds; }
    public Long getAlarmTimeSec() { return alarmTimeSec; }
    public void setAlarmTimeSec(Long alarmTimeSec) { this.alarmTimeSec = alarmTimeSec; }
    public Double getChangePointSec() { return changePointSec; }
    public void setChangePointSec(Double changePointSec) { this.changePointSec = changePointSec; }
    public String getVerdict() { return verdict; }
    public void setVerdict(String verdict) { this.verdict = verdict; }
    public String getTop1Service() { return top1Service; }
    public void setTop1Service(String top1Service) { this.top1Service = top1Service; }
    public String getTop1Indicator() { return top1Indicator; }
    public void setTop1Indicator(String top1Indicator) { this.top1Indicator = top1Indicator; }
    public String getConfidence() { return confidence; }
    public void setConfidence(String confidence) { this.confidence = confidence; }
    public Integer getRankGtService() { return rankGtService; }
    public void setRankGtService(Integer rankGtService) { this.rankGtService = rankGtService; }
    public Integer getRankGtIndicator() { return rankGtIndicator; }
    public void setRankGtIndicator(Integer rankGtIndicator) { this.rankGtIndicator = rankGtIndicator; }
    public Boolean getCorrectTop1() { return correctTop1; }
    public void setCorrectTop1(Boolean correctTop1) { this.correctTop1 = correctTop1; }
    public Boolean getCorrectTop3() { return correctTop3; }
    public void setCorrectTop3(Boolean correctTop3) { this.correctTop3 = correctTop3; }
    public Boolean getSymptomError() { return symptomError; }
    public void setSymptomError(Boolean symptomError) { this.symptomError = symptomError; }
    public long getTookMs() { return tookMs; }
    public void setTookMs(long tookMs) { this.tookMs = tookMs; }
    public String getBenchmarkJobId() { return benchmarkJobId; }
    public void setBenchmarkJobId(String benchmarkJobId) { this.benchmarkJobId = benchmarkJobId; }
    public String getResponseJson() { return responseJson; }
    public void setResponseJson(String responseJson) { this.responseJson = responseJson; }
    public String getExplanationJson() { return explanationJson; }
    public void setExplanationJson(String explanationJson) { this.explanationJson = explanationJson; }
    public String getWarnings() { return warnings; }
    public void setWarnings(String warnings) { this.warnings = warnings; }
}
