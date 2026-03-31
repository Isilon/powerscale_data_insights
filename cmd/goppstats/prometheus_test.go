package main

import (
	"testing"
	"time"
)

func TestCreateSampleID(t *testing.T) {
	t.Run("empty tags produce empty ID", func(t *testing.T) {
		id := CreateSampleID(map[string]string{})
		if id != "" {
			t.Errorf("got %q, want empty string", id)
		}
	})

	t.Run("single tag", func(t *testing.T) {
		id := CreateSampleID(map[string]string{"cluster": "mycluster"})
		if id != "cluster=mycluster" {
			t.Errorf("got %q, want %q", id, "cluster=mycluster")
		}
	})

	t.Run("multiple tags are sorted", func(t *testing.T) {
		id := CreateSampleID(map[string]string{
			"node":    "1",
			"cluster": "mycluster",
			"zone":    "System",
		})
		want := SampleID("cluster=mycluster,node=1,zone=System")
		if id != want {
			t.Errorf("got %q, want %q", id, want)
		}
	})

	t.Run("identical tags in different order produce same ID", func(t *testing.T) {
		tags1 := map[string]string{"a": "1", "b": "2", "c": "3"}
		tags2 := map[string]string{"c": "3", "a": "1", "b": "2"}
		if CreateSampleID(tags1) != CreateSampleID(tags2) {
			t.Error("same tags in different insertion order should produce same SampleID")
		}
	})

	t.Run("different tags produce different IDs", func(t *testing.T) {
		id1 := CreateSampleID(map[string]string{"cluster": "a"})
		id2 := CreateSampleID(map[string]string{"cluster": "b"})
		if id1 == id2 {
			t.Error("different tag values should produce different SampleIDs")
		}
	})
}

func TestAddSample(t *testing.T) {
	newFamily := func() *MetricFamily {
		return &MetricFamily{
			Samples:  make(map[SampleID]*Sample),
			LabelSet: make(map[string]int),
		}
	}

	t.Run("add new sample increments label counts", func(t *testing.T) {
		fam := newFamily()
		s := &Sample{Labels: map[string]string{"cluster": "c1", "node": "1"}}
		addSample(fam, s, "id1")
		if fam.LabelSet["cluster"] != 1 {
			t.Errorf("LabelSet[cluster] = %d, want 1", fam.LabelSet["cluster"])
		}
		if fam.LabelSet["node"] != 1 {
			t.Errorf("LabelSet[node] = %d, want 1", fam.LabelSet["node"])
		}
		if fam.Samples["id1"] != s {
			t.Error("sample not stored")
		}
	})

	t.Run("replacing sample adjusts label counts", func(t *testing.T) {
		fam := newFamily()
		old := &Sample{Labels: map[string]string{"cluster": "c1", "node": "1"}}
		addSample(fam, old, "id1")

		// Replace with sample that drops the "node" label
		new := &Sample{Labels: map[string]string{"cluster": "c2"}}
		addSample(fam, new, "id1")

		if fam.LabelSet["cluster"] != 1 {
			t.Errorf("LabelSet[cluster] = %d, want 1", fam.LabelSet["cluster"])
		}
		if fam.LabelSet["node"] != 0 {
			t.Errorf("LabelSet[node] = %d, want 0 (old label should be decremented)", fam.LabelSet["node"])
		}
		if fam.Samples["id1"] != new {
			t.Error("sample should be replaced with new value")
		}
	})
}

func TestUpdateDatasets(t *testing.T) {
	makeSink := func() *PrometheusSink {
		return &PrometheusSink{}
	}
	makeDs := func(id int, name string, creationTime int) DsInfoEntry {
		return DsInfoEntry{
			ID:           id,
			Name:         name,
			CreationTime: creationTime,
			Metrics:      []string{"username"},
		}
	}

	t.Run("initial call populates dsm", func(t *testing.T) {
		s := makeSink()
		di := &DsInfo{
			Datasets: []DsInfoEntry{makeDs(0, "System", 1000), makeDs(1, "ds1", 2000)},
		}
		s.UpdateDatasets(di)
		if s.dsm == nil {
			t.Fatal("dsm should not be nil after UpdateDatasets")
		}
		if _, ok := s.dsm[0]; !ok {
			t.Error("dsm[0] (System dataset) should be present")
		}
		if _, ok := s.dsm[1]; !ok {
			t.Error("dsm[1] should be present")
		}
	})

	t.Run("unchanged dataset is not modified", func(t *testing.T) {
		s := makeSink()
		di := &DsInfo{Datasets: []DsInfoEntry{makeDs(1, "ds1", 2000)}}
		s.UpdateDatasets(di)
		firstEntry := s.dsm[1]

		// Call again with same data
		s.UpdateDatasets(di)
		if s.dsm[1].ds.CreationTime != firstEntry.ds.CreationTime {
			t.Error("unchanged dataset should not be recreated")
		}
	})

	t.Run("dataset with new creation time is replaced", func(t *testing.T) {
		s := makeSink()
		di1 := &DsInfo{Datasets: []DsInfoEntry{makeDs(1, "ds1", 2000)}}
		s.UpdateDatasets(di1)

		di2 := &DsInfo{Datasets: []DsInfoEntry{makeDs(1, "ds1_new", 3000)}}
		s.UpdateDatasets(di2)

		if s.dsm[1].ds.CreationTime != 3000 {
			t.Errorf("creation time = %d, want 3000", s.dsm[1].ds.CreationTime)
		}
		if s.dsm[1].ds.Name != "ds1_new" {
			t.Errorf("name = %q, want ds1_new", s.dsm[1].ds.Name)
		}
	})

	t.Run("removed dataset is deleted", func(t *testing.T) {
		s := makeSink()
		di1 := &DsInfo{Datasets: []DsInfoEntry{makeDs(1, "ds1", 2000), makeDs(2, "ds2", 3000)}}
		s.UpdateDatasets(di1)

		// Second call without ds2
		di2 := &DsInfo{Datasets: []DsInfoEntry{makeDs(1, "ds1", 2000)}}
		s.UpdateDatasets(di2)

		if _, ok := s.dsm[2]; ok {
			t.Error("dsm[2] should have been removed")
		}
		if _, ok := s.dsm[1]; !ok {
			t.Error("dsm[1] should still be present")
		}
	})

	t.Run("new dataset is added on subsequent call", func(t *testing.T) {
		s := makeSink()
		di1 := &DsInfo{Datasets: []DsInfoEntry{makeDs(1, "ds1", 2000)}}
		s.UpdateDatasets(di1)

		di2 := &DsInfo{Datasets: []DsInfoEntry{makeDs(1, "ds1", 2000), makeDs(2, "ds2", 5000)}}
		s.UpdateDatasets(di2)

		if _, ok := s.dsm[2]; !ok {
			t.Error("dsm[2] should have been added")
		}
	})
}

func TestExpire(t *testing.T) {
	s := &PrometheusSink{
		fam: make(map[string]*MetricFamily),
	}

	past := time.Now().Add(-1 * time.Second)
	future := time.Now().Add(10 * time.Second)

	expiredSample := &Sample{
		Labels:     map[string]string{"cluster": "c1"},
		Expiration: past,
	}
	activeSample := &Sample{
		Labels:     map[string]string{"cluster": "c2"},
		Expiration: future,
	}

	fam := &MetricFamily{
		Samples:  make(map[SampleID]*Sample),
		LabelSet: make(map[string]int),
	}
	addSample(fam, expiredSample, "expired")
	addSample(fam, activeSample, "active")
	s.fam["test_metric"] = fam

	s.Expire()

	if _, ok := fam.Samples["expired"]; ok {
		t.Error("expired sample should have been removed")
	}
	if _, ok := fam.Samples["active"]; !ok {
		t.Error("active sample should remain")
	}
	// LabelSet for expired sample's labels should be decremented
	if fam.LabelSet["cluster"] != 1 {
		t.Errorf("LabelSet[cluster] = %d, want 1 (only active sample)", fam.LabelSet["cluster"])
	}
}
