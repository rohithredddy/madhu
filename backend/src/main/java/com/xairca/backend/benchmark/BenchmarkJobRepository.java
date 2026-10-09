package com.xairca.backend.benchmark;

import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

/** Stored benchmark jobs. */
public interface BenchmarkJobRepository extends JpaRepository<BenchmarkJob, String> {

    List<BenchmarkJob> findTop50ByOrderByCreatedAtDesc();
}
