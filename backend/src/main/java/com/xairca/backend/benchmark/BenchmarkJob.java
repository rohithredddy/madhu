package com.xairca.backend.benchmark;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Lob;
import java.time.Instant;

/** One benchmark job: a case filter x engines x delays, run in the background (docs/03 section 6). */
@Entity
public class BenchmarkJob {

    @Id
    private String id;
    private Instant createdAt;
    /** QUEUED, RUNNING, DONE or FAILED. */
    private String status;
    @Lob
    @Column(columnDefinition = "CLOB")
    private String filterJson;
    private String engines;
    private String delays;
    private int total;
    private int done;
    private int failed;
    @Lob
    @Column(columnDefinition = "CLOB")
    private String summaryJson;

    protected BenchmarkJob() {}

    public BenchmarkJob(String id, Instant createdAt, String filterJson, String engines, String delays, int total) {
        this.id = id;
        this.createdAt = createdAt;
        this.status = "QUEUED";
        this.filterJson = filterJson;
        this.engines = engines;
        this.delays = delays;
        this.total = total;
    }

    public String getId() { return id; }
    public Instant getCreatedAt() { return createdAt; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getFilterJson() { return filterJson; }
    public String getEngines() { return engines; }
    public String getDelays() { return delays; }
    public int getTotal() { return total; }
    public int getDone() { return done; }
    public void setDone(int done) { this.done = done; }
    public int getFailed() { return failed; }
    public void setFailed(int failed) { this.failed = failed; }
    public String getSummaryJson() { return summaryJson; }
    public void setSummaryJson(String summaryJson) { this.summaryJson = summaryJson; }
}
