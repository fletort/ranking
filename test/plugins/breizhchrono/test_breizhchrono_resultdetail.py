from ranking.plugins.breizhchrono.resultdetail import extract_result_detail


def test_extract_result_detail_returns_expected_fields() -> None:
    html = """
    <div class="container container-fluid pt-3 center-wrapper">
      <div class="row mt-2">
        <div class="col-12 col-md-6">
          <h1 class="title pb-2 text-center">CURIE Marie (N°0110)</h1>
          <div id="identity" class="mt-3 rounded-black">
            <div class="row">
              <span id="sex" title="Sexe : F">F</span>
              <span id="nat" title="Nationalité : FRA"><img src="/images/live-flags/FRA.jpg"></span>
              <span id="birth" title="Année de naissance : 1912">1912</span>
              <span id="categ" title="Catégorie : SE">SE</span>
            </div>
          </div>
        </div>
      </div>
      <div class="row mt-3 mt-md-4 justify-content-center">
        <div class="bloc-classement">
          <span class="classementTitle">Classement<br/>général</span>
          <span class="classementIndex"><img alt="1"/></span>
          <span class="classementTitle">/ 2134</span>
        </div>
        <div class="bloc-classement">
          <span class="classementTitle">Classement<br/>catégorie</span>
          <span class="classementIndex"><img alt="2"/></span>
          <span class="classementTitle">/ 512</span>
        </div>
        <div class="bloc-classement">
          <span class="classementTitle">Classement<br/>Sexe</span>
          <span class="classementIndex"><img alt="3"/></span>
          <span class="classementTitle">/ 1068</span>
        </div>
        <div>
          <span class="timeTitle">Temps Officiel</span>
          <span class="timeValue">00:29:40</span>
        </div>
        <div>
          <span class="secondaryTime">Temps Réel</span>
          <span class="secondaryTime">00:29:41</span>
        </div>
      </div>
    </div>
    """

    result = extract_result_detail(html)

    assert result == {
        "header_raw": "CURIE Marie (N°0110)",
        "sex": "F",
        "nationality": "FRA",
        "birth": "1912",
        "category": "SE",
        "rank_overall": "1",
        "rank_overall_total": "2134",
        "rank_category": "2",
        "rank_category_total": "512",
        "rank_gender": "3",
        "rank_gender_total": "1068",
        "time_official": "00:29:40",
        "time_real": "00:29:41",
    }


def test_extract_result_detail_handles_missing_data() -> None:
    assert extract_result_detail("<html><body></body></html>") == {}
